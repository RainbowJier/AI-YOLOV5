# Movement Algorithm Optimization (v2)

## Overview

The movement subsystem has been restructured for **clarity, modularity, and numerical stability**. The core logic remains unchanged, but refactored into discrete functions with explicit state management.

## Key Changes

### 1. **Modular Architecture**

Split the monolithic `aim_at()` into three focused functions:

- **`_update_track_state(x, y, h, dt)`** — EMA tracking + dual velocity estimation
  - Detects re-acquisition (jump or stale)
  - Updates box position and both velocity models
  - Returns reacquired flag + new state

- **`_compute_aim_point(bx, by, bh, cx, cy, firing)`** — Target prediction
  - Applies lead (one EMA lag) with proximity fade
  - Applies `lock_y` offset (except during firing)
  - Returns predicted (ax, ay) in screen space

- **`_compute_move(aim_x, aim_y, center_x, center_y, speed, dt, firing)`** — Movement output
  - Error fraction + world-velocity feed-forward
  - Deadband to reduce detector noise near lock
  - Soft tanh cap to prevent teleport
  - Returns (mx, my) in pixels

### 2. **Improved Numerics**

- **Vectorized clamping**: `np.clip()` replaces manual min/max chains
- **Safer zero divisions**: Explicit checks before divisions
- **Deadband scale**: Computed once per frame, reused
- **State consistency**: All updates atomic within a single function

### 3. **Better State Management**

- Global state now grouped logically:
  - Tracking: `_sx`, `_sy`, `_sh`, `_rx`, `_ry`, `_wx`, `_wy`, `_mx`, `_my`
  - Timing: `_last_t`
  - Target selection: `_stick_x`, `_stick_y`
  - Jump detection: `_strikes`
- Explicit state transitions (reacquired → clear all velocities)

### 4. **Debuggability**

- Clear function names describe intent
- Explicit intermediate variables (chase_x, chase_y, deadband_scale, fade)
- Comments explain the "why" at each step
- Easier to instrument with logging or telemetry

## Behavior (Unchanged)

The algorithm logic is **identical**; only the code structure changed:

### Dual Velocity Model

1. **Frame-relative velocity** (`_rx`, `_ry`): Compensates for EMA lag
   - Helps tracker catch up while target is moving
   - Resets on re-acquire

2. **World velocity** (`_wx`, `_wy`): Feed-forward prediction
   - Reconstructed from observed_delta + our_injected_move
   - Eliminates tracking lag when locked onto a strafing target
   - Self-cancels when perfectly locked (ideal observer)

### Movement Composition

```
move = error_fraction × chase_vector × deadband_scale + world_velocity × dt
```

Where:
- `error_fraction = 1 - exp(-rate × dt)` (time-normalized, feels same at 60/144 CPS)
- `chase_vector = aim_point - crosshair`
- `deadband_scale` removes jitter inside _DEADBAND radius
- World velocity term feeds forward target motion

### Soft Cap

```
move_clamped = cap × tanh(move / cap)
```

Prevents instant jumps on huge corrections while maintaining smooth ramp near zero.

## Performance

- **Same frame throughput**: No algorithmic changes
- **Better cache locality**: Grouped state vars
- **Vectorized ops**: `np.clip()` is faster than scalar min/max
- **Reduced branching**: Clearer flow, fewer deep nests

## Future Tuning Paths

### Adaptive Gain

```python
# In _compute_move(), could scale rate by confidence:
confidence = 1.0 - (chase_dist_sq / max_acquire_sq)
rate = config.move_rate * speed * confidence
```

### Directional Deadzones

```python
# Separate x/y deadbands for asymmetric control:
deadband_scale_x = max(0, abs(chase_x) - _DEADBAND_X) / abs(chase_x) if chase_x else 0
deadband_scale_y = max(0, abs(chase_y) - _DEADBAND_Y) / abs(chase_y) if chase_y else 0
```

### Velocity Smoothing

```python
# Low-pass filter on the combined move:
_mx_filtered = _mx_filtered + 0.2 * (_mx - _mx_filtered)
```

### Non-Linear Rate

```python
# Higher sensitivity near lock, gentler far away:
rate = config.move_rate * speed * (1 + 2 * deadband_scale) * speed
```

## Testing

- **Baseline**: Run with same config values, verify identical mouse moves
- **Re-acquire**: Rapid target switch → both should reset velocities identically
- **Sticky target**: Body+head flicker → should lock body, reach head with lock_y
- **Range gate**: Strafe in/out of aim_range → velocity estimate should stay warm
- **Firing**: LMB → move should speed up 3.0/2.6× and drop lock_y to center

---

**Last updated**: 2026-10-27  
**Restructured by**: Claude  
**Status**: Ready for integration  
