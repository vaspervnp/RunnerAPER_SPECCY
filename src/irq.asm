;; ===========================================================================
;; irq.asm - the 50 Hz heartbeat, IM 2 (after the Loukoumas port).
;;
;; The ULA raises one interrupt a frame, at the top of it. IM 1 would go to
;; #0038 in ROM, so it is IM 2 through a 257-byte table of IM2_FILL: whatever
;; byte the bus carries, the vector read is IM2_JUMP, where a JP to the
;; handler sits (config.asm says why it is not the table's own page).
;; ===========================================================================

;; ---------------------------------------------------------------------------
;; irq_init - the vector table, I, IM 2, interrupts on.
;; Destroys AF, BC, DE, HL.
;; ---------------------------------------------------------------------------
irq_init:
                di
                ld hl,IM2_TABLE
                ld de,IM2_TABLE+1
                ld bc,256
                ld (hl),IM2_FILL
                ldir                        ; 257 bytes
                ld a,#C3                    ; JP nn
                ld (IM2_JUMP),a
                ld hl,irq_handler
                ld (IM2_JUMP+1),hl
                ld a,IM2_I
                ld i,a
                im 2
                ei
                ret

;; ---------------------------------------------------------------------------
;; irq_handler - once a frame, at its top.
;; ---------------------------------------------------------------------------
irq_handler:
                push af
                push hl
                ld hl,frame_count
                inc (hl)
                pop hl
                pop af
                ei
                reti

;; ---------------------------------------------------------------------------
;; wait_game_frame - blocks until the interrupt that starts a game frame:
;; TV_PER_GAME interrupts after the one the last game frame started on. If
;; the work ran a little past it, the frame goes on at once (the blit waits
;; for the beam anyway); only whole TV frames lost count in missed_frames.
;; Returns C if it waited for the interrupt: the frame is then at its start.
;; Destroys AF, B, HL.
;; ---------------------------------------------------------------------------
wait_game_frame:
                ld hl,frame_last
                ld a,(frame_count)          ; already due if the work ran past
                sub (hl)                    ; the interrupt (the blit can
                cp TV_PER_GAME              ; still make it)
                jr nc,.due
.wait:          halt
                ld a,(frame_count)
                sub (hl)
                cp TV_PER_GAME
                jr c,.wait
                call .due
                scf
                ret
.due:
                sub TV_PER_GAME
                jr z,.on_time
                ld b,a                      ; frames lost
                ld a,(missed_frames)
                add a,b
                jr nc,.count
                ld a,255
.count:         ld (missed_frames),a
.on_time:       ld a,(frame_count)
                ld (hl),a
                or a
                ret

frame_count:    defb 0                      ; +1 every interrupt
frame_last:     defb 0                      ; frame_count when the game frame began
missed_frames:  defb 0                      ; saturates at 255
