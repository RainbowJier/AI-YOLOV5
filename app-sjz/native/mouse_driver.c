/*
 * mouse_driver.dll - relative mouse movement for the aimbot.
 *
 * Why a DLL at all:
 *   win32api.mouse_event() is a per-call Python->C transition plus a
 *   user32 lookup on every frame. This exports one flat function that
 *   fills the SendInput struct directly, keeps fractional leftovers
 *   between calls (the aim loop feeds float deltas that int() would
 *   truncate to zero on small corrections), and can raise the process
 *   timer resolution so injected input is not delayed behind the
 *   default 15.6 ms scheduler tick.
 *
 * Exports (all cdecl, x64):
 *   int  md_init(void)                 1 on success. Call once.
 *   void md_shutdown(void)             Undo md_init.
 *   int  md_move(float dx, float dy)   Relative move, positive right/down.
 *                                      Returns 1 if the OS accepted the input.
 *   int  md_move_exact(int dx, int dy) No fractional accumulation.
 *   int  md_set_timer_resolution(unsigned ms) 0 restores the default.
 *   int  md_get_sent(void)             Inputs accepted since md_init.
 *
 * Build: the cl line in docs/DRIVER.md (VS x64 dev prompt).
 * Source stays pure ASCII: cl reads it back through the OEM code page
 * (936 on zh-CN systems) and non-ASCII comments trigger warning C4819.
 */

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmsystem.h>

#define MD_EXPORT __declspec(dllexport)

static volatile LONG g_inited = 0;
static volatile LONG g_sent = 0;
static volatile LONG g_timer_set = 0;
static volatile LONG g_timer_set_prev = 0;
static float g_frac_x = 0.0f;
static float g_frac_y = 0.0f;

MD_EXPORT int md_set_timer_resolution(unsigned ms);

static int md_send(int dx, int dy)
{
    INPUT in;
    ZeroMemory(&in, sizeof(in));
    in.type = INPUT_MOUSE;
    in.mi.dx = dx;
    in.mi.dy = dy;
    in.mi.dwFlags = MOUSEEVENTF_MOVE;
    in.mi.time = 0;
    in.mi.dwExtraInfo = 0;

    if (SendInput(1, &in, sizeof(in)) != 1)
        return 0;
    InterlockedIncrement(&g_sent);
    return 1;
}

MD_EXPORT int md_init(void)
{
    if (InterlockedCompareExchange(&g_inited, 1, 0) == 0) {
        g_frac_x = 0.0f;
        g_frac_y = 0.0f;
        InterlockedExchange(&g_sent, 0);
    }
    return 1;
}

MD_EXPORT void md_shutdown(void)
{
    if (InterlockedExchange(&g_inited, 0) != 0)
        md_set_timer_resolution(0);
}

MD_EXPORT int md_move(float dx, float dy)
{
    /* Accumulate the sub-pixel remainder so a stream of 0.4 px
       corrections still reaches the screen instead of flooring to 0. */
    g_frac_x += dx;
    g_frac_y += dy;

    int ix = (int)g_frac_x;
    int iy = (int)g_frac_y;
    g_frac_x -= (float)ix;
    g_frac_y -= (float)iy;

    if (ix == 0 && iy == 0)
        return 1; /* nothing owed to the OS yet; not an error */
    return md_send(ix, iy);
}

MD_EXPORT int md_move_exact(int dx, int dy)
{
    if (dx == 0 && dy == 0)
        return 1;
    return md_send(dx, dy);
}

MD_EXPORT int md_set_timer_resolution(unsigned ms)
{
    if (ms == 0) {
        if (InterlockedExchange(&g_timer_set, 0) != 0)
            timeEndPeriod((UINT)InterlockedCompareExchange(&g_timer_set_prev, 0, 0));
        return 1;
    }
    /* timeBeginPeriod is global to the process media timer; remember the
       request so shutdown only undoes what we started. */
    if (timeBeginPeriod(ms) == TIMERR_NOERROR) {
        InterlockedExchange(&g_timer_set_prev, (LONG)ms);
        InterlockedExchange(&g_timer_set, (LONG)ms);
        return 1;
    }
    return 0;
}

MD_EXPORT int md_get_sent(void)
{
    return (int)InterlockedCompareExchange(&g_sent, 0, 0);
}
