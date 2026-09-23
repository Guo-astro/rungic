/* A visible GTK4/GLES exercise, not just a driver enumeration. */
#include <gtk/gtk.h>
#include <epoxy/gl.h>
#include <stdio.h>
static GtkWidget *window;
static gboolean render(GtkGLArea *area, GdkGLContext *context, gpointer data) {
    (void)context;(void)data;
    static gboolean reported;
    const char *renderer=(const char*)glGetString(GL_RENDERER);
    if(!reported) {
        GskRenderer *gsk=gtk_native_get_renderer(GTK_NATIVE(window));
        printf("GTK scene renderer: %s\nGL renderer: %s\nGL version: %s\n", G_OBJECT_TYPE_NAME(gsk),renderer,glGetString(GL_VERSION));fflush(stdout);
        reported=TRUE;
    }
    int width=gtk_widget_get_width(GTK_WIDGET(area))*gtk_widget_get_scale_factor(GTK_WIDGET(area));
    int height=gtk_widget_get_height(GTK_WIDGET(area))*gtk_widget_get_scale_factor(GTK_WIDGET(area));
    glEnable(GL_SCISSOR_TEST);
    glScissor(0,0,width/2,height);glClearColor(1,0,0,1);glClear(GL_COLOR_BUFFER_BIT);
    glScissor(width/2,height/2,width-width/2,height-height/2);glClearColor(0,1,0,1);glClear(GL_COLOR_BUFFER_BIT);
    glScissor(width/2,0,width-width/2,height/2);glClearColor(0,0,1,1);glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);
    return TRUE;
}
static gboolean quit(gpointer data){g_application_quit(G_APPLICATION(data));return G_SOURCE_REMOVE;}
static void activate(GtkApplication *app,gpointer data) {
    (void)data;window=gtk_application_window_new(app);gtk_window_set_title(GTK_WINDOW(window),"Adreno GPU check");gtk_window_set_default_size(GTK_WINDOW(window),360,600);
    GtkWidget *box=gtk_box_new(GTK_ORIENTATION_VERTICAL,12);gtk_window_set_child(GTK_WINDOW(window),box);
    gtk_box_append(GTK_BOX(box),gtk_label_new("Adreno 710 · GTK4 · GLES\n左红 / 右上绿 / 右下蓝"));
    GtkWidget *area=gtk_gl_area_new();gtk_gl_area_set_use_es(GTK_GL_AREA(area),TRUE);gtk_gl_area_set_required_version(GTK_GL_AREA(area),3,2);gtk_widget_set_vexpand(area,TRUE);gtk_box_append(GTK_BOX(box),area);g_signal_connect(area,"render",G_CALLBACK(render),NULL);
    gtk_window_present(GTK_WINDOW(window));g_timeout_add_seconds(15,quit,app);
}
int main(int argc,char **argv){GtkApplication *app=gtk_application_new("dev.moto.GpuCheck",G_APPLICATION_NON_UNIQUE);g_signal_connect(app,"activate",G_CALLBACK(activate),NULL);int status=g_application_run(G_APPLICATION(app),argc,argv);g_object_unref(app);return status;}
