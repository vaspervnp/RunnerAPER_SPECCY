; =============================================================================
; Collisions: what the runner stands on and what it runs into (the CPC's
; src/collide.asm and collide_c7.asm, without the moving trains and with the
; signals always red: the Spectrum has no ink cycling).
;
; Two probes on the runner's lane (the lane whose centre is nearest):
;   feet  (FOOT_Y-1)  - support level S of that cell:
;                       train/nose = 2, ramp up row k = k, ramp down row k = 2-k,
;                       anything else = 0
;   front (FOOT_Y-5)  - obstacles: stop needs z >= 1, train/nose z >= 2,
;                       red signal z >= 3
; On the ground the base follows S one step at a time (ramps); a drop of 2
; (end of a train) plays a short fall. Landing from a jump onto a higher
; level is only allowed if the jump was at least that high.
;
; Game states: RUN, CRASHED (crash animation, scroll stopped), GAME_OVER
; (then the score screen, src/screens.asm).
; =============================================================================

STATE_RUN       equ 0
STATE_CRASHED   equ 1
STATE_GAME_OVER equ 2

LIVES_START     equ 3
CRASH_FRAMES    equ 40                  ; 1.6 s
INVULN_FRAMES   equ 50                  ; 2 s
GAME_OVER_FRAMES equ 75                 ; 3 s
FEET_PROBE      equ FOOT_Y-1
FRONT_PROBE     equ FOOT_Y-5

; -----------------------------------------------------------------------------
; cell_at: HL = screen line, A = lane -> A = collision class (low nibble),
; B = ramp row (high nibble). Destroys C, DE, HL.
; -----------------------------------------------------------------------------
cell_at:
                ld c,a
                ld a,(cur_j)                ; picture line -> picture row
                add a,l
                ld l,a
                jr nc,.nc
                inc h
.nc:            and 7                       ; (the line in the row)
                ld (.y),a
                srl h
                rr l
                srl l
                srl l
                ex de,hl                    ; world row = top - picture row
                ld hl,(cur_top_row)
                or a
                sbc hl,de
                ld (probe_row),hl
                call desc_addr
                ld a,D_COLL
                add a,c
                call add_a_hl
                ld a,(hl)
                ld b,a
                srl b
                srl b
                srl b
                srl b
                and 15
                ret
.y:             defb 0

; A = class, B = ramp row -> A = support level S
support_level:
                cp COL_GAP                  ; between two wagons: a roof, or
                jr nz,.not_gap              ; in hard mode a gap to jump
                ld a,(gap_hard)
                or a
                jr z,.roof
                xor a
                ret
.not_gap:       cp COL_TRAIN
                jr z,.roof
                cp COL_NOSE
                jr z,.roof
                cp COL_RAMP_UP
                jr z,.up
                cp COL_RAMP_DOWN
                jr z,.down
                xor a
                ret
.roof:          ld a,2
                ret
.up:            ld a,b
                ret
.down:          ld a,2
                sub b
                ret

; A = lane under the runner (nearest lane centre)
runner_lane:
                ld a,(player_centre)
                sub COL_LANE1
                ld c,LANE_W
                ld b,0
.div:           sub c
                ret c                       ; (B returned in A below)
                inc b
                jr .div

; -----------------------------------------------------------------------------
; collide: after player_update. May change player_base/z, start a fall or
; a crash. (The CPC kept it in bank C7: collide_c7.asm.)
; -----------------------------------------------------------------------------
collide:
                call runner_lane
                ld a,b
                ld (probe_lane),a

                ; --- support under the feet ---
                ld hl,FEET_PROBE
                call cell_at
                ld hl,(probe_row)
                ld (feet_row),hl
                call support_level
                ld (support),a

                ld hl,(arc_ptr)
                ld a,h
                or l
                jr nz,.airborne

                ld a,(was_airborne)         ; landing this frame?
                or a
                jr z,.walking
                xor a
                ld (was_airborne),a
                ld a,(support)              ; land on S if the jump reached it
                ld b,a
                ld a,(prev_z)
                cp b
                jp c,.crash_feet            ; jumped into the side of a train
                ld a,(player_base)
                cp b
                jp z,.front
                jr c,.set_base              ; landed higher (roof)
                ld a,b                      ; landed lower: fall the rest
                jr .drop

.walking:       ld a,(support)
                ld b,a
                ld a,(player_base)
                cp b
                jr z,.front
                jr nc,.lower
                inc a                       ; higher: one ramp step at a time
                cp b
                jp nz,.crash_feet           ; walked into a train
.set_base:      ld a,b
                ld (player_base),a
                ld (player_z),a
                jr .front
.lower:         ld a,b                      ; ground dropped away
.drop:          ld c,a
                ld a,(player_base)
                sub c
                ld b,a                      ; B = drop
                ld a,c
                ld (player_base),a
                ld a,b
                cp 2
                jr c,.small_drop
                ld hl,arc_fall              ; visible fall from the roof
                ld (arc_ptr),hl
                xor a
                ld (arc_index),a
                ld a,c
                add 2
                ld (player_z),a
                ld a,1
                ld (was_airborne),a
                jr .front
.small_drop:    ld a,c
                ld (player_z),a
                jr .front

.airborne:      ld a,(player_z)             ; descending onto a higher level
                ld b,a                      ; (springs: land on a roof)?
                ld a,(prev_z)
                cp b
                jr c,.rising
                jr z,.rising
                ld c,a                      ; C = prev_z > z
                ld a,(support)
                cp b
                jr c,.rising                ; still above the level
                ld d,a                      ; D = S >= z
                ld a,c
                cp d
                jr c,.rising                ; was below it last frame
                ld a,(player_base)
                cp d
                jr nc,.rising               ; not higher than the base
                ld hl,0
                ld (arc_ptr),hl
                xor a
                ld (was_airborne),a
                ld a,d
                ld (player_base),a
                ld (player_z),a
                jp .front
.rising:        ld a,1
                ld (was_airborne),a
                ld a,b
                ld (prev_z),a

                ; --- obstacles at the front ---
.front:         ld a,(invuln)
                or a
                ret nz
                ld a,(probe_lane)
                ld hl,FRONT_PROBE
                call cell_at
                ld hl,(probe_row)
                ld (front_row),hl
                ld b,a
                ld a,(player_z)
                ld c,a
                ld a,b
                cp COL_STOP
                jr z,.need1
                cp COL_TRAIN
                jr z,.need2
                cp COL_NOSE
                jr z,.need2
                cp COL_GAP
                jr z,.need2
                cp COL_SIGNAL
                ret nz
                ld a,(signal_red)
                or a
                ret z
                ld a,c                      ; red: only a jump from a roof clears it
                cp 3
                ret nc
                jp crash
.need2:         ld a,c
                cp 2
                ret nc
                jp crash
.need1:         ld a,c
                or a
                ret nz
                jp crash
.crash_feet:    ld a,(invuln)
                or a
                jp z,crash
                ld a,(support)              ; protected: just take that level
                ld (player_base),a
                ld (player_z),a
                ret


; fall from a roof: length, z per frame (base already lowered)
arc_fall:       defb 2, 1,1

; -----------------------------------------------------------------------------
; crash: lose a life, play the crash, stop the scroll.
; -----------------------------------------------------------------------------
crash:
                ld a,(no_crash)             ; test/debug switch
                or a
                ret nz
                ld a,SFX_CRASH              ; also when the helmet takes it
                ld (sfx_request),a
                ld a,(helmet)               ; helmet: absorbs this one
                or a
                jr z,.hurt
                xor a
                ld (helmet),a
                ld a,INVULN_FRAMES
                ld (invuln),a
                ret
.hurt:
                ld a,STATE_CRASHED
                ld (game_state),a
                ld a,CRASH_FRAMES
                ld (state_timer),a
                ld hl,0
                ld (arc_ptr),hl
                ld a,(move_steps_left)      ; hit while changing lanes: back
                or a                        ; to the lane without the obstacle
                jr z,.centre
                ld a,(probe_lane)
                ld b,a
                ld a,(player_lane)          ; (the lane moved to)
                cp b
                jr nz,.centre               ; hit in the lane left: go on to it
                ld a,(move_dir)
                ld b,a
                ld a,(player_lane)
                sub b
                ld (player_lane),a
.centre:        ld a,(player_lane)          ; on the lane's centre
                ld (probe_lane),a
                ld b,a
                ld a,LANE_CENTRE1
                inc b
                jr .times_test
.times:         add LANE_W
.times_test:    djnz .times
                ld (player_centre),a
                xor a
                ld (was_airborne),a
                ld (move_steps_left),a
                ld (move_queued),a
                ld a,(player_base)
                ld (player_z),a
                ld hl,lives
                dec (hl)
                ld hl,crashes
                inc (hl)
                ret

; -----------------------------------------------------------------------------
; game_state_update: timers of CRASHED / GAME_OVER. Returns Z if the runner
; plays normally this frame.
; -----------------------------------------------------------------------------
game_state_update:
                ld a,(invuln)
                or a
                jr z,.no_invuln
                dec a
                ld (invuln),a
.no_invuln:     ld a,(game_state)
                or a
                ret z
                ld hl,state_timer
                dec (hl)
                jr nz,.busy
                cp STATE_GAME_OVER
                jr z,.new_run
                ld a,(lives)                ; crash over
                or a
                jr z,.game_over
                xor a
                ld (game_state),a
                ld a,INVULN_FRAMES
                ld (invuln),a
                ld a,(probe_lane)           ; stand on whatever is under us
                ld hl,FEET_PROBE
                call cell_at
                call support_level
                ld (player_base),a
                ld (player_z),a
.busy:          ld hl,anim_tick             ; keep the crash animation going
                inc (hl)
                or 1                        ; NZ: no normal play this frame
                ret
.game_over:     ld a,STATE_GAME_OVER
                ld (game_state),a
                ld a,GAME_OVER_FRAMES
                ld (state_timer),a
                or 1
                ret
.new_run:       call game_finished      ; score screen (or the menu after a demo)
                or 1
                ret

; --- state ---------------------------------------------------------------------
game_state:     defb STATE_RUN
state_timer:    defb 0
lives:          defb LIVES_START
crashes:        defb 0                  ; total, for tests
invuln:         defb 0
support:        defb 0
probe_lane:     defb 0
was_airborne:   defb 0
prev_z:         defb 0
signal_red:     defb 1                  ; always red on the Spectrum
no_crash:       defb 0                  ; debug: obstacles never crash the runner
probe_row:      defw 0                  ; world rows last probed (for tests)
feet_row:       defw 0
front_row:      defw 0
