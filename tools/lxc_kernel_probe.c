/* Bounded Android/aarch64 LXC prerequisite probes. No libc dependency.
 * Mount tests run in a new, private mount namespace. BPF tests attach only
 * to an empty, dedicated test cgroup and move only this helper into it.
 * Do not run against an existing application/Android cgroup.
 */
typedef unsigned int u32;
typedef unsigned long u64;
static long call(long n,long a,long b,long c,long d,long e,long f) {
    register long x8 __asm__("x8")=n;
    register long x0 __asm__("x0")=a;
    register long x1 __asm__("x1")=b;
    register long x2 __asm__("x2")=c;
    register long x3 __asm__("x3")=d;
    register long x4 __asm__("x4")=e;
    register long x5 __asm__("x5")=f;
    __asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory","cc");
    return x0;
}
#define S(n,a,b,c,d,e) call(n,(long)(a),(long)(b),(long)(c),(long)(d),(long)(e),0)
static long length(const char *s) { long n=0;while(s[n])n++;return n; }
static void put(const char *s) { S(64,1,s,length(s),0,0); }
static void number(long v) {
    char buf[32];int n=0;if(v<0){put("-");v=-v;}
    do{buf[n++]=(char)('0'+v%10);v/=10;}while(v);
    while(n)S(64,1,&buf[--n],1,0,0);
}
static long report(const char *name,long rc) { put(name);put("=");number(rc);put("\n");return rc; }
static int same(const char *a,const char *b) { while(*a&&*a==*b){a++;b++;}return *a==*b; }
static int prefix(const char *a,const char *b) { while(*b){if(*a++!=*b++)return 0;}return 1; }
static void path(char *out,const char *base,const char *tail) {
    while(*base)*out++=*base++;while(*tail)*out++=*tail++;*out=0;
}
static long open_file(const char *p,long flags) { return S(56,-100,p,flags,0600,0); }
static void close_file(long fd) { if(fd>=0)S(57,fd,0,0,0,0); }
static long mount_fs(const char *src,const char *dst,const char *type,long flags,const char *opts) {
    return S(40,src,dst,type,flags,opts);
}
static char paths[12][512];
static int mounts(const char *base) {
    if(!prefix(base,"/data/local/tmp/moto-lxc-audit-"))return 2;
    if(report("unshare_mount",S(97,0x20000,0,0,0,0))<0)return 1;
    /* Source and filesystem arguments must be NULL for propagation changes. */
    if(report("mount_private_root",mount_fs(0,"/",0,(1L<<18)|(1L<<14),0))<0)return 1;
    const char *names[]={"/lower","/upper","/work","/merged","/ram","/pts","/proc","/root","/bind"};
    for(int i=0;i<9;i++){path(paths[i],base,names[i]);S(34,-100,paths[i],0700,0,0);}
    report("bind_directory",mount_fs(paths[0],paths[8],0,4096,0));
    long rc=report("mount_tmpfs",mount_fs("tmpfs",paths[4],"tmpfs",0,"size=4m"));
    if(rc==0){
        path(paths[9],paths[4],"/null");
        report("mknod_tmpfs",S(33,-100,paths[9],0020000|0600,259,0));
        long fd=report("open_tmpfs_device",open_file(paths[9],2));close_file(fd);
    }
    rc=report("mount_devpts_newinstance",mount_fs("devpts",paths[5],"devpts",0,"newinstance,ptmxmode=0666,mode=0620"));
    if(rc==0){
        path(paths[9],paths[5],"/ptmx");
        long fd=report("open_pty",open_file(paths[9],2|0400));
        if(fd>=0){int zero=0;report("unlock_pty",S(29,fd,0x40045431,&zero,0,0));close_file(fd);}
    }
    report("mount_proc",mount_fs("proc",paths[6],"proc",0,0));
    path(paths[9],paths[0],"/file");long fd=open_file(paths[9],1|0100|01000);
    if(fd>=0){S(64,fd,"lower",5,0,0);close_file(fd);}
    char options[1600];path(options,"lowerdir=",paths[0]);
    path(options+length(options),",upperdir=",paths[1]);
    path(options+length(options),",workdir=",paths[2]);
    rc=report("mount_overlay_f2fs",mount_fs("overlay",paths[3],"overlay",0,options));
    if(rc==0){
        path(paths[9],paths[3],"/file");fd=report("overlay_open_copyup",open_file(paths[9],1|01000));
        if(fd>=0){report("overlay_write",S(64,fd,"upper",5,0,0));close_file(fd);}
    }
    if(report("mount_pivot_rootfs",mount_fs("tmpfs",paths[7],"tmpfs",0,"size=4m"))==0){
        path(paths[9],paths[7],"/old");S(34,-100,paths[9],0700,0,0);
        if(report("chdir_new_root",S(49,paths[7],0,0,0,0))==0){
            if(report("pivot_root",S(41,".","old",0,0,0))==0){
                S(49,"/",0,0,0,0);report("detach_old_root",S(39,"/old",2,0,0,0));
            }
        }
    }
    return 0;
}
struct insn { unsigned char code,regs;short off;int imm; };
struct load_attr {
    u32 type,count;u64 insns,license;u32 log_level,log_size;u64 log_buf;
    u32 version,flags;char name[16];u32 ifindex,attach_type;
};
struct attach_attr {u32 target_fd,prog_fd,type,flags,replace_fd;};
static char verifier[8192];
static int bpf_device(const char *cg) {
    if(!prefix(cg,"/sys/fs/cgroup/moto-lxc-probe-"))return 2;
    /* Deny all device opens for this helper while inside the test cgroup. */
    struct insn program[]={{0xb7,0,0,0},{0x95,0,0,0}};
    struct load_attr load={0};load.type=15;load.count=2;load.insns=(u64)program;
    load.license=(u64)"GPL";load.log_level=1;load.log_size=sizeof(verifier);load.log_buf=(u64)verifier;
    load.attach_type=6;
    long fd=report("bpf_device_prog_load",S(280,5,&load,sizeof(load),0,0));
    if(fd<0){put(verifier);return 1;}
    long cfd=report("open_test_cgroup",open_file(cg,0));
    if(cfd<0){close_file(fd);return 1;}
    struct attach_attr attr={(u32)cfd,(u32)fd,6,0,0};
    long attached=report("bpf_device_attach",S(280,8,&attr,sizeof(attr),0,0));
    if(attached==0){
        path(paths[0],cg,"/cgroup.procs");long procs=open_file(paths[0],1);
        long moved=report("move_only_probe_to_cgroup",procs<0?procs:S(64,procs,"0",1,0,0));close_file(procs);
        if(moved>=0){long dev=report("open_dev_null_with_deny_expected_minus1",open_file("/dev/null",0));close_file(dev);}
        report("bpf_device_detach",S(280,9,&attr,sizeof(attr),0,0));
        long dev=report("open_dev_null_after_detach",open_file("/dev/null",0));close_file(dev);
    }
    close_file(cfd);close_file(fd);return attached<0;
}
static int seccomp(void) {
    struct classic {unsigned short code;unsigned char jt,jf;u32 k;} instruction={6,0,0,0x7fff0000};
    struct filter {unsigned short count;const void *ptr;} filter={1,&instruction};
    if(report("no_new_privileges",S(167,38,1,0,0,0))<0)return 1;
    return report("seccomp_allow_filter",S(277,1,0,&filter,0,0))<0;
}
void probe_main(long *sp) {
    long argc=sp[0];char **argv=(char **)(sp+1);int rc=2;
    if(argc==2&&same(argv[1],"seccomp"))rc=seccomp();
    if(argc==3&&length(argv[2])<350&&same(argv[1],"mounts"))rc=mounts(argv[2]);
    if(argc==3&&length(argv[2])<350&&same(argv[1],"bpf-device"))rc=bpf_device(argv[2]);
    S(93,rc,0,0,0,0);for(;;);
}
__attribute__((naked,noreturn)) void _start(void) {
    __asm__ volatile("mov x0, sp\nb probe_main\n");
}
