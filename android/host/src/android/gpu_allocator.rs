//! Private allocator bridge: Android owns AHardwareBuffers, Phoc renders to their
//! DMA-BUFs. A per-buffer socket lease keeps ownership until wlroots destroys it.
use std::{collections::HashMap, ffi::c_void, io::Read, os::{fd::AsRawFd, unix::{net::{UnixListener, UnixStream}, fs::PermissionsExt}}, sync::{Arc, Mutex, OnceLock, Weak, atomic::{AtomicBool, AtomicUsize, Ordering}}};
use jni::{JNIEnv, objects::{JClass, JString}, sys::jboolean};
#[repr(C)]
#[derive(Default)]
struct Desc { width:u32, height:u32, layers:u32, format:u32, usage:u64, stride:u32, rfu0:u32, rfu1:u64 }
#[repr(C)]
struct Handle { version:i32, num_fds:i32, num_ints:i32, data:[i32;0] }
#[link(name="android")]
extern "C" {
    fn AHardwareBuffer_allocate(desc:*const Desc, out:*mut *mut c_void)->i32;
    fn AHardwareBuffer_describe(buffer:*const c_void, desc:*mut Desc);
    fn AHardwareBuffer_getNativeHandle(buffer:*const c_void)->*const Handle;
    fn AHardwareBuffer_release(buffer:*mut c_void);
}
pub(crate) struct Buffer { pub ptr:*mut c_void, width:u32, height:u32, fourcc:u32 }
unsafe impl Send for Buffer {}
unsafe impl Sync for Buffer {}
impl Drop for Buffer { fn drop(&mut self) { unsafe { AHardwareBuffer_release(self.ptr) }; } }
type Key=(u64,u64);
fn registry()->&'static Mutex<HashMap<Key,Weak<Buffer>>> { static R:OnceLock<Mutex<HashMap<Key,Weak<Buffer>>>>=OnceLock::new();R.get_or_init(||Mutex::new(HashMap::new())) }
fn key(fd:i32)->Option<Key> { let mut s=unsafe {std::mem::zeroed::<libc::stat>()};if unsafe{libc::fstat(fd,&mut s)}!=0 {None} else {Some((s.st_dev as u64,s.st_ino as u64))} }
pub(crate) fn lookup(fd:i32,width:i32,height:i32,fourcc:u32)->Option<Arc<Buffer>> { let k=key(fd)?;let b=registry().lock().ok()?.get(&k)?.upgrade()?;if b.width==width as u32 && b.height==height as u32 && b.fourcc==fourcc {Some(b)} else {None} }
/// DRM_FORMAT_MOD_QCOM_COMPRESSED: Adreno UBWC, metadata plane first.
const MOD_QCOM_COMPRESSED:u64=0x0500000000000001;
/// Qualcomm gralloc's GRALLOC_USAGE_PRIVATE_ALLOC_UBWC (AHARDWAREBUFFER_USAGE_VENDOR_0).
const USAGE_ALLOC_UBWC:u64=1<<28;
fn align(v:u64,a:u64)->u64 { v.div_ceil(a)*a }
/// Size of an RGBA8888 UBWC allocation (msm_media_info RGBA8888_UBWC, which is
/// also Mesa's fdl6 layout): 16x4-pixel metadata tiles, 64x16 aligned, then pixels.
fn ubwc_size(w:u32,h:u32,stride_px:u32)->u64 {
    let meta=align(align(w.div_ceil(16) as u64,64)*align(h.div_ceil(4) as u64,16),4096);
    meta+align(stride_px as u64*4*align(h as u64,16),4096)
}
fn serve(mut stream:UnixStream)->std::io::Result<()> {
    stream.set_read_timeout(Some(std::time::Duration::from_secs(5)))?;
    // v1: magic 'UPGM', width, height, fourcc. v2: magic 'VPGM', the same, then the
    // wanted modifier (u64); the reply adds the modifier actually allocated.
    let mut request=[0u8;24];stream.read_exact(&mut request[..16])?;
    let word=|r:&[u8;24],i:usize|u32::from_le_bytes(r[i..i+4].try_into().unwrap());
    let v2=word(&request,0)==0x4d475056;
    if v2 {stream.read_exact(&mut request[16..])?;}
    let (magic,w,h,format)=(word(&request,0),word(&request,4),word(&request,8),word(&request,12));
    let wanted=if v2 {u64::from_le_bytes(request[16..24].try_into().unwrap())} else {0};
    if (magic!=0x4d475055 && !v2) || w==0 || h==0 || w>4096 || h>4096 || w as u64*h as u64>4_194_304 {return Err(std::io::ErrorKind::InvalidInput.into());}
    // Only XBGR/ABGR (R,G,B,A bytes) -> AHARDWAREBUFFER_FORMAT_R8G8B8A8. HAL BGRA_8888 (5)
    // crashed SurfaceFlinger's RenderEngine when it GPU-composited a zero-copy layer.
    let ahb_format=match format {0x34324258|0x34324241=>1,_=>{log::warn!("RUNGIC_GPU: unsupported format 0x{:x} (use XB24/AB24)",format);return Err(std::io::ErrorKind::InvalidInput.into())}};
    // CPU usage forces an uncompressed linear allocation, shared with Mesa. UBWC
    // needs Qualcomm's private usage bit and no CPU access (0xB00: GPU sampled and
    // color output, composer overlay).
    // COMPOSER_OVERLAY (1<<11): required for buffers given to ASurfaceTransaction_setBuffer
    // (zero-copy presentation, surface_control.rs); the framework adds it only to its own buffers.
    let ubwc=wanted==MOD_QCOM_COMPRESSED;
    let usage=if ubwc {0xB00|USAGE_ALLOC_UBWC} else {0xB33};
    let desc=Desc{width:w,height:h,layers:1,format:ahb_format,usage,..Default::default()};
    let mut ptr=std::ptr::null_mut();let result=unsafe{AHardwareBuffer_allocate(&desc,&mut ptr)};
    if result!=0 || ptr.is_null() {log::warn!("RUNGIC_GPU: AHB allocation failed {} format={} {}x{}",result,ahb_format,w,h);return Err(std::io::ErrorKind::Other.into());}
    let b=Arc::new(Buffer{ptr,width:w,height:h,fourcc:format});
    let mut actual=Desc::default();unsafe{AHardwareBuffer_describe(ptr,&mut actual)};
    let handle=unsafe{AHardwareBuffer_getNativeHandle(ptr)};
    if handle.is_null() || unsafe{(*handle).num_fds}<1 {return Err(std::io::ErrorKind::Other.into());}
    let fd=unsafe{*(*handle).data.as_ptr()};let k=key(fd).ok_or(std::io::ErrorKind::Other)?;
    // Report UBWC only when the buffer has exactly the UBWC layout Mesa will assume;
    // gralloc may fall back to linear (then the client renders linear).
    let size=unsafe{libc::lseek(fd,0,libc::SEEK_END)} as u64;
    let modifier=if ubwc && size==ubwc_size(w,h,actual.stride) {MOD_QCOM_COMPRESSED} else {0};
    if ubwc && modifier==0 {log::warn!("RUNGIC_GPU: UBWC requested but gralloc returned {} bytes (expected {})",size,ubwc_size(w,h,actual.stride));}
    registry().lock().unwrap().insert(k,Arc::downgrade(&b));
    let mut reply=[0u8;20];reply[0..4].copy_from_slice(&magic.to_le_bytes());reply[4..8].copy_from_slice(&(actual.stride*4).to_le_bytes());reply[8..12].copy_from_slice(&format.to_le_bytes());
    reply[12..20].copy_from_slice(&modifier.to_le_bytes());
    let reply_len=if v2 {20} else {12};
    let sent=unsafe {
        let mut iov=libc::iovec{iov_base:reply.as_mut_ptr().cast(),iov_len:reply_len};
        let mut control=[0usize;8];let mut msg=std::mem::zeroed::<libc::msghdr>();
        msg.msg_iov=&mut iov;msg.msg_iovlen=1;msg.msg_control=control.as_mut_ptr().cast();msg.msg_controllen=libc::CMSG_SPACE(4) as usize;
        let c=libc::CMSG_FIRSTHDR(&msg);(*c).cmsg_level=libc::SOL_SOCKET;(*c).cmsg_type=libc::SCM_RIGHTS;(*c).cmsg_len=libc::CMSG_LEN(4) as usize;std::ptr::write_unaligned(libc::CMSG_DATA(c).cast::<i32>(),fd);
        libc::sendmsg(stream.as_raw_fd(),&msg,libc::MSG_NOSIGNAL)
    };
    if sent==reply_len as isize {
        log::warn!("RUNGIC_GPU: AHB allocated {}x{} stride={} format=0x{:x} modifier=0x{:x}",w,h,actual.stride*4,format,modifier);
        stream.set_read_timeout(None)?;let mut byte=[0];let _=stream.read(&mut byte);
    }
    registry().lock().unwrap().remove(&k);drop(b);Ok(())
}
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_startGpuAllocator(mut env:JNIEnv,_class:JClass,path:JString)->jboolean {
    static STARTED:AtomicBool=AtomicBool::new(false);
    static LIVE:AtomicUsize=AtomicUsize::new(0);
    if STARTED.load(Ordering::Acquire) {return 1;}
    let path:String=match env.get_string(&path) {Ok(p)=>p.into(),Err(_)=>return 0};
    let _=std::fs::remove_file(&path);
    let listener=match UnixListener::bind(&path) {Ok(l)=>l,Err(e)=>{log::error!("GPU allocator: {}",e);return 0;}};
    if std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o666)).is_err() {return 0;}
    STARTED.store(true,Ordering::Release);
    std::thread::spawn(move||{for stream in listener.incoming() {if let Ok(stream)=stream {
        if LIVE.fetch_add(1,Ordering::AcqRel)>=32 {LIVE.fetch_sub(1,Ordering::AcqRel);continue;}
        std::thread::spawn(move||{if let Err(e)=serve(stream){log::warn!("GPU allocator request: {}",e);}LIVE.fetch_sub(1,Ordering::AcqRel);});
    } } });1
}
