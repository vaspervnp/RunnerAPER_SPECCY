; =============================================================================
; Sound (planzx.md M9): the CPC's tunes and effects (music/*.txt,
; tools/mkmusic.py -> src/data/music.asm).
;
; 128K (an AY found at boot): as on the CPC, the tune on channels A (melody)
; and B (bass), the effects on C, in steps of 1/50 s. The CPC stepped them
; from an interrupt; here the blit sits through every other one, so
; sound_frame takes the game frame's two steps one after the other and the
; AY hears the second (a note's length is still right to 1/50 s).
;
; 48K: the beeper takes the processor while it sounds. In a game an effect
; is a short burst a game frame (its step's note for about BEEP_BURST_T);
; on the still screens there is time, and the tune's melody plays most of
; every frame.
;
; The tune follows game_mode: TUNE_GAME while playing (and in the demo),
; TUNE_OVER once on the game over screen, TUNE_MENU on the other screens.
; sound_on = 0 or a pause silences everything; music_on = 0 (M while
; playing, MUSIC in the menu) only the tunes.
; =============================================================================

AY_SELECT       equ #FFFD
AY_WRITE        equ #BFFD
MIXER_BASE      equ %00111000           ; tones on, noise off
MIXER_TONE_C    equ %00000100           ; 1 = tone C off
MIXER_NOISE_C   equ %00100000           ; 0 = noise C on
AY_REGS         equ 11                  ; R0-R10 (no envelope)
SPEAKER         equ %00010000           ; port #FE: the beeper (border black)
BEEP_MENU_T     equ 60000               ; the melody on a still screen: a frame's
SFX_STEP        equ 7                   ; bytes an effect's step

; channel record (IX)
CH_PTR          equ 0                   ; (2) next event
CH_START        equ 2                   ; (2) loop point
CH_TICKS        equ 4                   ; ticks left of the note
CH_VOL          equ 5
CH_PERIOD       equ 6                   ; (2)
CH_REG          equ 8                   ; its period register (0 / 2)
CH_VOLREG       equ 9                   ; its volume register (8 / 9)
CH_TOP          equ 10                  ; volume at the start of a note
CH_FLOOR        equ 11                  ; decays down to this
CH_NOTE         equ 12                  ; the note sounding (0: none)

; -----------------------------------------------------------------------------
; sound_init: an AY? (port #FFFD reads back the register it was given; on a
; 48K it is the floating bus). Interrupts on.
; -----------------------------------------------------------------------------
sound_init:
                halt                        ; (in the border: the bus reads #FF)
                ld bc,AY_SELECT
                xor a
                out (c),a                   ; register 0
                ld b,AY_WRITE>>8
                ld a,#55
                out (c),a
                ld b,AY_SELECT>>8
                in a,(c)
                cp #55
                jr nz,.none
                ld b,AY_WRITE>>8
                ld a,#AA
                out (c),a
                ld b,AY_SELECT>>8
                in a,(c)
                cp #AA
                jr nz,.none
                ld a,1
                ld (ay_present),a
                ret
.none:          xor a
                ld (ay_present),a
                ret

; -----------------------------------------------------------------------------
; sound_frame: once a game frame.
; -----------------------------------------------------------------------------
sound_frame:
                ld a,(ay_present)
                or a
                jp z,beeper_frame
                call sound_tick
                ; fall through: two steps a game frame

; one 1/50 s step on the AY. Destroys AF, BC, DE, HL, IX.
sound_tick:
                call tune_tick
                call sfx_tick
                ld a,(sound_on)
                or a
                jr z,.mute
                ld a,(paused)
                or a
                jr nz,.mute
                ld a,(music_on)             ; M: music off, effects on
                or a
                jr nz,ay_flush
                ld (ay_shadow+8),a
                ld (ay_shadow+9),a
                jr ay_flush
.mute:          xor a
                ld (ay_shadow+8),a
                ld (ay_shadow+9),a
                ld (ay_shadow+10),a
                ; fall through

; ay_shadow -> AY, only the registers that changed since the last flush
ay_flush:
                ld hl,ay_shadow
                ld de,ay_last
                ld a,0                      ; A = register
.reg:           ex af,af'
                ld a,(de)
                cp (hl)
                jr z,.same
                ld a,(hl)
                ld (de),a
                ex af,af'
                ld bc,AY_SELECT
                out (c),a
                ex af,af'
                ld b,AY_WRITE>>8
                out (c),a
.same:          ex af,af'
                inc hl
                inc de
                inc a
                cp AY_REGS
                jr nz,.reg
                ret

; the tune for this screen, its channels a step on
tune_tick:
                ld b,TUNE_GAME
                ld a,(game_mode)
                cp MODE_MENU
                jr c,.chosen
                ld b,TUNE_OVER
                cp MODE_OVER
                jr z,.chosen
                ld b,TUNE_MENU
.chosen:        ld a,(snd_tune)
                cp b
                call nz,start_tune
                ld ix,chan_a
                call channel_tick
                ld ix,chan_b
                jp channel_tick

; B = tune: both channels from its start
start_tune:
                ld a,b
                ld (snd_tune),a
                add a,a
                add a,a
                ld hl,tune_table
                call add_a_hl
                ld ix,chan_a
                call .channel
                ld ix,chan_b
.channel:       ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (ix+CH_PTR),e
                ld (ix+CH_PTR+1),d
                ld (ix+CH_START),e
                ld (ix+CH_START+1),d
                ld (ix+CH_TICKS),1          ; the first note on this tick
                ret

; IX = channel: next note when the current one ends, volume decay, shadow
channel_tick:
                dec (ix+CH_TICKS)
                jr z,.next
                ld a,(ix+CH_TICKS)          ; last tick of a note: half volume
                dec a                       ; (notes do not run together)
                ld a,(ix+CH_VOL)
                jr nz,.decay
                srl a
                jr .set_vol
.decay:         cp (ix+CH_FLOOR)
                jr c,.shadow
                jr z,.shadow
                dec a
.set_vol:       ld (ix+CH_VOL),a
                jr .shadow
.next:          ld l,(ix+CH_PTR)
                ld h,(ix+CH_PTR+1)
                ld a,(hl)
                cp TUNE_LOOP
                jr nz,.not_loop
                ld l,(ix+CH_START)
                ld h,(ix+CH_START+1)
                ld a,(hl)
.not_loop:      cp TUNE_STOP
                jr nz,.note
                ld (ix+CH_TICKS),1          ; stays on the end mark, silent
                ld (ix+CH_VOL),0
                ld (ix+CH_NOTE),0
                jr .shadow
.note:          inc hl
                ld c,a                      ; C = note (0 = rest)
                ld (ix+CH_NOTE),a
                ld a,(hl)
                inc hl
                ld (ix+CH_TICKS),a
                ld (ix+CH_PTR),l
                ld (ix+CH_PTR+1),h
                ld a,c
                or a
                jr z,.rest
                dec a
                add a,a
                ld hl,note_periods
                call add_a_hl
                ld a,(hl)
                ld (ix+CH_PERIOD),a
                inc hl
                ld a,(hl)
                ld (ix+CH_PERIOD+1),a
                ld a,(ix+CH_TOP)
                ld (ix+CH_VOL),a
                jr .shadow
.rest:          ld (ix+CH_VOL),0
.shadow:        ld hl,ay_shadow
                ld a,(ix+CH_REG)
                call add_a_hl
                ld a,(ix+CH_PERIOD)
                ld (hl),a
                inc hl
                ld a,(ix+CH_PERIOD+1)
                ld (hl),a
                ld hl,ay_shadow
                ld a,(ix+CH_VOLREG)
                call add_a_hl
                ld a,(ix+CH_VOL)
                ld (hl),a
                ret

; effects: takes sfx_request, a step on (channel C's shadow; the beeper
; reads the step from sfx_now)
sfx_tick:
                ld a,(sfx_request)
                or a
                jr z,.run
                ld c,a
                xor a
                ld (sfx_request),a
                ld a,c                      ; entry = sfx_table + 3 * (n - 1)
                dec a
                ld b,a
                add a,a
                add a,b
                ld hl,sfx_table
                call add_a_hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld b,(hl)                   ; B = priority
                ld hl,(sfx_ptr)             ; one playing with a higher one?
                ld a,h
                or l
                jr z,.take
                ld a,(sfx_prio)
                ld c,a
                ld a,b
                cp c
                jr c,.run
.take:          ld (sfx_ptr),de
                ld a,b
                ld (sfx_prio),a
.run:           ld hl,(sfx_ptr)
                ld a,h
                or l
                jr z,.quiet
                ld (sfx_now),hl
                ld e,(hl)                   ; DE = period
                inc hl
                ld d,(hl)
                inc hl
                ld a,(hl)                   ; A = volume | flags
                inc hl
                ld c,(hl)                   ; C = noise period
                cp SFX_END
                jr z,.done
                ld b,a
                ld a,SFX_STEP-3
                call add_a_hl
                ld (sfx_ptr),hl
                ld (ay_shadow+4),de
                ld a,b
                and 15
                ld (ay_shadow+10),a
                ld a,c
                ld (ay_shadow+6),a
                ld a,MIXER_BASE
                bit 7,b                     ; SFX_TONE_OFF
                jr z,.tone
                or MIXER_TONE_C
.tone:          bit 6,b                     ; SFX_NOISE_ON
                jr z,.mixer
                and MIXER_NOISE_C^#FF
.mixer:         ld (ay_shadow+7),a
                ret
.done:          ld hl,0
                ld (sfx_ptr),hl
.quiet:         ld hl,0
                ld (sfx_now),hl
                xor a
                ld (ay_shadow+10),a
                ld a,MIXER_BASE
                ld (ay_shadow+7),a
                ret

; -----------------------------------------------------------------------------
; The beeper (48K)
; -----------------------------------------------------------------------------
beeper_frame:
                ld a,(game_mode)            ; the tune: the still screens'
                cp MODE_MENU                ; only
                jr c,.no_tune
                call tune_tick
                call tune_tick
.no_tune:       call sfx_tick               ; the effect, two steps on
                call sfx_tick
                ld a,(sound_on)
                or a
                ret z
                ld a,(paused)
                or a
                ret nz
                ld a,(game_mode)            ; a still screen: the melody
                cp MODE_MENU
                jr nc,.melody
                ld hl,(sfx_now)            ; in a game: the effect's step
                ld a,h
                or l
                ret z
                ld e,(hl)                   ; (its period: tone or noise?)
                inc hl
                ld d,(hl)
                inc hl
                ld a,(hl)
                inc hl
                ld c,(hl)                   ; C = noise period
                inc hl
                bit 7,a                     ; SFX_TONE_OFF: noise
                jr nz,.noise
                ld e,(hl)                   ; DE = the beeper's count
                inc hl
                ld d,(hl)
                inc hl
                ld b,(hl)                   ; B = half waves
                jp beep_halves
.noise:         ld a,c                      ; noise: a few random clicks,
                srl a                       ; further apart the higher its
                srl a                       ; period
                add a,4
                ld e,a
                ld d,0
                ld b,6
                jp beep_noise
.melody:        ld a,(music_on)
                or a
                ret z
                ld a,(chan_a+CH_NOTE)
                or a
                ret z                       ; (a rest)
                dec a
                add a,a
                ld hl,beep_counts
                call add_a_hl
                ld e,(hl)
                inc hl
                ld d,(hl)                   ; DE = its count
                ld hl,BEEP_MENU_T
                ; fall through

; DE = count, HL = T-states: the note for as long (whole half waves)
beep_for:
                push hl
                ld hl,BEEP_EXTRA_T          ; HL = T a half: 26 * count + 67
                ld b,BEEP_LOOP_T
.mul:           add hl,de
                djnz .mul
                ld b,h
                ld c,l
                pop hl
                xor a                       ; A = the halves that fit
.count:         or a
                sbc hl,bc
                jr c,.counted
                inc a
                jr nz,.count
                dec a
.counted:       or a
                ret z
                ld b,a
                ; fall through

; DE = count, B = half waves: the beeper. Destroys AF, BC, HL.
beep_halves:
                ld a,(beep_state)
                ld h,a
.half:          ld a,h                      ; 26 T to the OUT and after it
                xor SPEAKER
                ld h,a
                out (#FE),a
                push bc                     ; (the rest: BEEP_EXTRA_T)
                ld b,d
                ld c,e
.delay:         dec bc                      ; BEEP_LOOP_T a turn
                ld a,b
                or c
                jr nz,.delay
                pop bc
                djnz .half
                ld a,h
                ld (beep_state),a
                ret

; DE = count, B = clicks: the beeper at random
beep_noise:
                ld a,(beep_state)
                ld h,a
.click:         call random
                and SPEAKER
                xor h
                ld h,a
                out (#FE),a
                push bc
                ld b,d
                ld c,e
.delay:         dec bc
                ld a,b
                or c
                jr nz,.delay
                pop bc
                djnz .click
                ld a,h
                ld (beep_state),a
                ret

; --- state ---------------------------------------------------------------------
ay_present:     defb 0
beep_state:     defb 0                  ; what the speaker bit was left at
sfx_request:    defb 0                  ; the effect asked for (SFX_*)
sfx_now:       defw 0                  ; the step being played (0: none)
snd_tune:       defb #FF                ; tune playing (#FF: none yet)
chan_a:         defw 0,0                ; ptr, start
                defb 1,0                ; ticks, volume
                defw 0                  ; period
                defb 0,8,13,9           ; period reg, volume reg, top, floor
                defb 0                  ; note
chan_b:         defw 0,0
                defb 1,0
                defw 0
                defb 2,9,12,8
                defb 0
sfx_ptr:        defw 0                  ; 0: no effect
sfx_prio:       defb 0
ay_shadow:      defs 7,0                ; R0-R6
                defb MIXER_BASE         ; R7
                defs 3,0                ; R8-R10
ay_last:        defs AY_REGS,#FF        ; what the AY holds (#FF: write it)

                include "data/music.asm"
