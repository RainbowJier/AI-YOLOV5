# Movement Algorithm (v3.1: error-space damped spring)

## Why v3.1

v3.0 simulated a crosshair position and chased it with a spring. The
simulation assumed injected dots move the view by exactly the predicted
pixels — open loop. Any mismatch (wrong `lock_sen`, a view that ignores
input, a dead driver) let the *simulated* crosshair arrive while the
real one stood still → output decayed to zero → "mouse stopped moving".

v3.1 removes the position entirely. One state variable per axis: a
spring **velocity** driven by the freshly OBSERVED error every frame:

```
v'  = (v + dt * omega^2 * e) / (1 + 2*omega*dt)   critically damped
e   = observed error, deadband-gated              (0 inside deadband_px)
out = v * dt, v soft-capped                        (max_move_speed)
```

Closed loop by construction: if the view does not respond, the error
never shrinks, v saturates against the cap, and the mouse keeps pushing.
A sensitivity mismatch only slows convergence — it can never stall.

## Why v3 (the original rewrite)

v2 mixed two terms every frame:

```
move = error_fraction * chase + world_velocity * dt
                                ^^^ bypasses the deadband
```

The world-velocity term bypassed the deadband. Near lock, detector noise
(±1-2 px) differentiated into a fake velocity (dividing by dt multiplies
it by ~60) and was injected straight into the mouse every frame — the
constant shake. v2's `track_tau = 0.019` at 60 fps only filtered ~41% of
that noise, so the aim point itself wobbled.

## Anti-shake structure (v3.1)

- **EMA** (`track_tau`) absorbs detector box jitter before anything moves.
- **World velocity** (observed delta + our own injected move) drives a
  lead that is **noise-gated**: below `lead_min_speed` px/s the lead is
  *exactly zero* — a standing target gets no feed-forward at all.
- **Radial deadband** (`deadband_px`): inside it the error is zero → the
  spring velocity decays exponentially → output is exactly 0.
- **Critically damped spring**: no overshoot on any input; the internal
  velocity state decays to zero, so nothing in the loop amplifies noise.
- **tanh soft cap** (`max_move_speed`): huge corrections glide, not jump.
- **Sticky selection + 35% hysteresis**: no head/body flip-flop between
  overlapping boxes.
- **Firing (LMB)**: spring stiffness boosted 3.0/2.6x (tighter lock).

## Movement flow per frame

1. `pick()` → team filter (numpy, host).
2. `closest()` → sticky + hysteresis target selection.
3. `_update_track()` → EMA box + world velocity + jump detection.
4. `aim_at()` → gates (CapsLock, LMB, range) → `_aim_point()` (lead gated
   by `_lead_gate()`, faded by `lead_fade_radius`, offset by `lock_y`) →
   radial deadband → spring velocity step → soft cap → `mouse.move()`.

## Config knobs (app-cs2/config.py)

| knob | meaning | shake? | tune |
| --- | --- | --- | --- |
| `move_rate` | spring stiffness (`× speed`) | lower = calmer | 4–12 |
| `track_tau` | box EMA smoothing | higher = calmer | 0.015–0.05 |
| `deadband_px` | hard-hold radius | higher = calmer | 1–4 |
| `lead_min_speed` | lead noise gate | higher = calmer | 30–80 |
| `lead_fade_radius` | lead fade near crosshair | lower = calmer | 8–16 |
| `max_move_speed` | soft cap | — | 2400–7200 |
| `lock_sen` | px → mouse dots | — | game sens scale |
| `lock_y` | vertical lock point | — | 0=top 0.2=head 1=bottom |

Still shaking? Raise `deadband_px` → 2.5–4 first, then `lead_min_speed`
→ 50–80. Lags behind strafing? Raise `move_rate`.

## Simulation tests

`scripts/sim_movement.py` runs the real state machine against a
closed-loop view model (the box moves as the view rotates; a `gain`
factor can break the loop — 0 = dead view, 0.5 = sensitivity mismatch):

- stationary + ±0.8px noise → 0.43 px residual, 0.0000 dots/frame jitter
- step input → converges, 1.0 px overshoot
- 30 px/s strafe → 3.4 px steady-state error
- **dead view (gain=0)** → still pushing 13.8 dots/frame after 4 s
  (v3.0 regression: output must never decay when the view ignores input)
- **half sensitivity (gain=0.5)** → still converges to 0.72 px
  (v3.0 regression: wrong lock_sen must not stall)
- LMB held → zero output; release → instant resume
- overlapping head/body boxes → one stable pick (hysteresis)
- CapsLock off → full state reset

