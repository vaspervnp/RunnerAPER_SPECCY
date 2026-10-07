;; ===========================================================================
;; video.asm - the world's ring and the picture (planzx.md 2.2, 2.3).
;;
;; The world is drawn row by row into a ring in uncontended RAM, never on the
;; screen. Every game frame blit copies the 192 lines of the picture from the
;; ring to the playfield, by POP/PUSH batches. The copy is slower than the
;; beam (some 400 T a line to its 224), so it starts once the beam has
;; fetched line 0 (beam_sync) and stays behind it all the way down: the
;; first frame of the game frame shows the old picture whole, the second the
;; new one whole. The sprites are drawn into each character row as the copy
;; finishes it (sprites_row), and the next blit takes them away. The
;; attributes go in once a frame, in the border gap (blit_attrs).
;;
;; Where the picture is: screen line y shows line (y + cur_j) & 7 of world row
;; cur_top_row - ((y + cur_j) >> 3), as on the CPC. The world moves down by
;; lowering cur_j; below 0 it is a coarse step, a new world row at the top.
;; ===========================================================================

RING_END_H      equ (ring+RING_BYTES)>>8

;; ---------------------------------------------------------------------------
;; slot_addr - A = slot -> HL = its first byte in the ring (slot * 192).
;; Destroys DE.
;; ---------------------------------------------------------------------------
slot_addr:
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                   ; * 64
                ld d,h
                ld e,l
                add hl,hl                   ; * 128
                add hl,de                   ; * 192
                ld de,ring
                add hl,de
                ret

;; ---------------------------------------------------------------------------
;; attr_slot_addr - A = slot -> HL = its attribute line (slot * 24).
;; Destroys DE.
;; ---------------------------------------------------------------------------
attr_slot_addr:
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                   ; * 8
                ld d,h
                ld e,l
                add hl,hl                   ; * 16
                add hl,de                   ; * 24
                ld de,attr_ring
                add hl,de
                ret

;; ---------------------------------------------------------------------------
;; A row's slot is never worked out from its 16-bit number: the slot of the
;; picture's top row is kept (top_slot) and the others are counted from it.
;;
;; slot_below - A = slot -> A = the slot of the world row below it (one lower
;; row number: one slot further on). Destroys nothing else.
;; ---------------------------------------------------------------------------
slot_below:
                inc a
                cp RING_SLOTS
                ret c
                xor a
                ret

;; slot_above - the world row above (a row number higher: a slot back).
slot_above:
                or a
                jr nz,.back
                ld a,RING_SLOTS
.back:          dec a
                ret

;; ---------------------------------------------------------------------------
;; ring_done - after a row was drawn into slot A: the shadow copy if it is
;; slot 0. Destroys BC, DE, HL.
;; ---------------------------------------------------------------------------
ring_done:
                or a
                ret nz
                ld hl,ring                  ; slot 0: and the shadow after the end
                ld de,ring+RING_BYTES
                ld bc,ROW_PIXELS
.shadow:        repeat 16
                ldi
                rend
                jp pe,.shadow               ; (LDI: P/V while BC is not 0)
                ret

;; ---------------------------------------------------------------------------
;; beam_sync - returns once the ULA has started the picture: the floating bus
;; (port #FF) reads #FF over the border and the bytes the ULA fetches while it
;; draws, and no attribute is ever #FF. Gives up after SYNC_LIMIT turns on a
;; machine without one (+2A/+3). Destroys AF, BC.
;; ---------------------------------------------------------------------------
beam_sync:
                ld bc,SYNC_LIMIT
beam_sync_bc:
.poll:          ld a,#FF
                in a,(#FF)
                inc a
                ret nz
                dec bc
                ld a,b
                or c
                jr nz,.poll
                ld hl,sync_timeouts
                inc (hl)
                ret
;; ---------------------------------------------------------------------------
;; beam_sync_late - beam_sync for a game frame that began late (the work ran
;; past its interrupt, so where the beam is is not known). If the ULA is
;; already drawing the picture, a blit now would run ahead of the beam and
;; tear it: so it waits for the picture's end and syncs to the next one's
;; line 0, a TV frame later. Either way, an interrupt passed meanwhile makes
;; that one the game frame's start (frame_last), its lost frame counted.
;; Destroys AF, BC, D, HL.
;; ---------------------------------------------------------------------------
LATE_SAMPLES    equ 24                  ; 37 T apart: 2+ attributes in any
                                        ; 24 samples of the picture (48/128K)
LATE_LIMIT      equ 600                 ; beam_sync turns: past the border
                                        ; between two pictures (26.9K T)
beam_sync_late:
                call .burst
                jr z,.border                ; all #FF: not in the picture
.in_picture:    call .burst                 ; wait for the bottom border
                jr nz,.in_picture
                ld bc,LATE_LIMIT
                call beam_sync_bc
                jr .rephase
.border:        call beam_sync
.rephase:       ld hl,frame_last
                ld a,(frame_count)
                sub (hl)
                ret z
                ld b,a
                ld a,(frame_count)
                ld (hl),a
                ld a,(missed_frames)
                add a,b
                jr nc,.count
                ld a,255
.count:         ld (missed_frames),a
                ret

;; LATE_SAMPLES reads of the floating bus ANDed: Z if all were #FF
.burst:         ld bc,LATE_SAMPLES*256+#FF
                ld d,c
.sample:        in a,(c)                    ; 12
                and d                       ; 4
                ld d,a                      ; 4
                nop                         ; 4
                djnz .sample                ; 13: 37 T a sample
                inc a
                ret

;; ---------------------------------------------------------------------------
;; blit - the picture from the ring to the playfield, character row by
;; character row, and the attributes of all of them at once. Call it right
;; after beam_sync. Destroys everything.
;;
;; A line is read with POP from the ring and written with PUSH to the screen:
;; a PUSH writes its two bytes with one contended access each, where LDI pays
;; three (the write and two cycles on DE). Eight words fit in the registers,
;; so the ring is read in batches of 16 bytes, three for every two lines,
;; and keeps an even line (of its slot) as columns 8-23 then 0-7, an odd line
;; in column order. An even line and the odd one after it:
;;   columns 8-23 of the even line        -> IX = the even line + 24
;;   columns 0-7 of both                  -> IY = the even line + 8, and +256
;;   columns 8-23 of the odd line         -> IX + 256
;; so two pointers do, and a batch's SP is saved and loaded three times for
;; two lines (not four). When cur_j is even, the screen's lines go in such
;; pairs inside every character row (blit_even); when odd, the first line of
;; each character row is the odd line of a pair begun on the row above, and
;; its last line the even one of a pair ended on the row below (blit_odd).
;;
;; With SP in the ring and the screen, interrupts are off for the whole of it
;; (some 75K T), and the interrupt of the game frame's second TV frame is
;; never taken: blit counts it itself. It always falls inside: the blit starts
;; after T 14336 and runs well past T 69888.
;;
;; After each character row, the sprites' lines in it (src/sprite.asm).
;;
;; The attributes of a character row are those of the world row that has the
;; most of its 8 lines: the top one while cur_j <= 4, else the one below. They
;; are all written after pixel row ATTR_AFTER - 1, in the gap between the
;; first TV frame's picture (it ends by T 57.3K) and the second's (from T
;; 84.2K): there no row is being shown, and the screen is not contended. Only
;; when they change: those rows move on, or attr_dirty (a row in the picture
;; drawn again).
;; ---------------------------------------------------------------------------
ATTR_AFTER      equ 14                      ; 14 pixel rows: past T 60K
RING_SPLIT      equ 8                       ; an even line: from this column

;; 16 bytes from the ring: four words, then four into the other registers
macro BATCH_IN
                ld sp,(blit_src)
                pop af
                pop bc
                pop de
                pop hl
                exx
                ex af,af'
                pop af
                pop bc
                pop de
                pop hl
                ld (blit_src),sp
mend
;; four words to SP, then the other four below them
macro PUSH4
                push hl
                push de
                push bc
                push af
mend
macro SWAP
                exx
                ex af,af'
mend
;; an even line (IX, IY) and the odd line under it: IX, IY a line down
;; twice. (Nothing that changes the flags between a POP AF and its PUSH: the
;; INCs come where the registers in use are pushed already.)
macro PAIR
                BATCH_IN                    ; even 8-23
                ld sp,ix
                PUSH4
                SWAP
                PUSH4
                BATCH_IN                    ; even 0-7, odd 0-7
                SWAP
                ld sp,iy
                PUSH4
                inc iyh
                inc ixh
                SWAP
                ld sp,iy
                PUSH4
                BATCH_IN                    ; odd 8-23
                ld sp,ix
                PUSH4
                SWAP
                PUSH4
                inc ixh
                inc iyh
mend

blit:
                ld a,(cur_j)                ; attributes: the top row's, or the
                cp 5                        ; row's below it: from slot A
                ld a,(cur_top_row)
                ld c,a
                ld a,(top_slot)
                jr c,.top
                call slot_below
                dec c
.top:           ld b,a
                ld a,(attr_dirty)           ; anything new?
                or a
                jr nz,.attrs
                ld a,(attr_key)
                cp c
                ld a,0
                jr z,.same
.attrs:         xor a
                ld (attr_dirty),a
                ld a,c
                ld (attr_key),a
                ld a,b
                call attr_slot_addr
                ld a,1
.same:          ld (blit_attr_src),hl       ; (HL meaningless when A = 0)
                ld (blit_attr_on),a
                ld a,(top_slot)             ; pixels: the top row's slot, from
                call slot_addr              ; its line cur_j
                ld a,(cur_j)
                ld e,a
                add a,a
                add a,e
                add a,a
                add a,a
                add a,a                     ; j * 24
                ld e,a
                ld d,0
                add hl,de
                ld (blit_src),hl
                ld a,PICTURE_ROWS
                ld (blit_rows),a
                ld hl,spr_rowmark           ; the sprites' rows: marked
                ld (blit_markp),hl
                ld ix,SCR_BITMAP+PLAY_W
                ld iy,SCR_BITMAP+RING_SPLIT
                ld (blit_sp),sp
                ld a,(cur_j)
                rra
                jp c,blit_odd
                di

;; --- cur_j even: four pairs a character row -----------------------------------
blit_even:
                PAIR
                PAIR
                PAIR
                PAIR
                ld a,ixl                    ; the next character row: +32,
                add a,32                    ; the next third on a carry
                ld ixl,a
                ld a,iyl
                add a,32
                ld iyl,a
                ld a,ixh
                jr nc,.third
                add a,8
.third:         sub 8
                ld ixh,a
                ld iyh,a
                ld sp,(blit_sp)
                call blit_row_done
                jp nz,blit_even
                jp blit_end

;; --- cur_j odd: the screen's first line is an odd one: its columns 0-7 now,
;; and a character row is then: the rest of its first line, three pairs, and
;; the first two batches of a pair whose odd line is the next row's first.
blit_odd:
                di
                ld sp,(blit_src)            ; (blit_src: the odd line)
                pop af
                pop bc
                pop de
                pop hl
                ld (blit_src),sp
                ld sp,iy
                PUSH4
.row:           BATCH_IN                    ; the first line's 8-23
                ld sp,ix
                PUSH4
                SWAP
                PUSH4
                inc ixh
                inc iyh
                PAIR
                PAIR
                PAIR
                BATCH_IN                    ; the last line's 8-23
                ld sp,ix
                PUSH4
                SWAP
                PUSH4
                BATCH_IN                    ; its 0-7, and the next row's
                SWAP                        ; first line's 0-7
                ld sp,iy
                PUSH4
                ld a,ixh                    ; the next character row (with
                sub 7                       ; the free registers)
                ld h,a
                ld a,ixl
                add a,32
                ld ixl,a
                ld a,iyl
                add a,32
                ld iyl,a
                ld a,h
                jr nc,.third
                add a,8
.third:         ld ixh,a
                ld iyh,a
                ld a,(blit_rows)            ; (none after the last)
                dec a
                jr z,.last
                SWAP
                ld sp,iy
                PUSH4
.last:          ld sp,(blit_sp)
                call blit_row_done
                jp nz,.row

blit_end:       ld sp,(blit_sp)
                ld hl,frame_count           ; the interrupt it sat through
                inc (hl)
                ei
                ret

;; blit_row_done - a character row's pixels written (SP back on the stack):
;; the ring's end passed (the lines in between came from the shadow), the
;; attributes' turn, the sprites in the row. NZ while rows are left. Keeps
;; IX, IY.
blit_row_done:
                ld hl,(blit_src)            ; past the ring's end: back round
                ld a,h
                cp RING_END_H
                jr c,.ring
                sub RING_BYTES>>8
                ld h,a
                ld (blit_src),hl
.ring:          ld a,(blit_rows)            ; the attributes' turn?
                cp PICTURE_ROWS+1-ATTR_AFTER
                jr nz,.no_attrs
                ld a,(blit_attr_on)
                or a
                call nz,blit_attrs
.no_attrs:      ld hl,(blit_markp)          ; sprites in this row: drawn on it
                ld a,(spr_stamp)            ; now (src/sprite.asm)
                cp (hl)
                inc hl
                ld (blit_markp),hl
                jr nz,.no_sprites
                push ix
                push iy
                ld a,PICTURE_ROWS
                ld hl,blit_rows
                sub (hl)
                call sprites_row
                pop iy
                pop ix
.no_sprites:    ld hl,blit_rows
                dec (hl)
                ret

;; blit_attrs - every character row's attributes from blit_attr_src: 24
;; bytes each, the rows of the ring one after the other, round from its end
;; to its start. Destroys AF, BC, DE, HL.
ATTR_RING_END   equ ATTR_RING_ORG+ATTR_RING_BYTES
blit_attrs:
                ld hl,(blit_attr_src)
                ld de,SCR_ATTR
                ld b,PICTURE_ROWS
.row:           ld c,255                    ; (C high enough for the LDIs)
                repeat PLAY_W
                ldi
                rend
                ld a,l                      ; the ring's end: its start
                cp ATTR_RING_END & #FF
                jr nz,.in
                ld a,h
                cp ATTR_RING_END>>8
                jr nz,.in
                ld hl,ATTR_RING_ORG
.in:            ld a,e
                add a,32-PLAY_W
                ld e,a
                jr nc,.same
                inc d
.same:          djnz .row
                ret

blit_src:       defw 0
blit_sp:        defw 0
blit_attr_src:  defw 0
blit_attr_on:   defb 0                      ; the attributes to be written
attr_key:       defb 0                      ; low byte of the world row they
                                            ; were from, for character row 0
attr_dirty:     defb 1                      ; a row in the picture drawn again
blit_rows:      defb 0
blit_markp:     defw 0


;; ---------------------------------------------------------------------------
;; scroll_init - the picture's top at world row PICTURE_ROWS, line 0.
;; ---------------------------------------------------------------------------
scroll_init:
                xor a
                ld (cur_j),a
                ld a,RING_SLOTS-PICTURE_ROWS ; (-PICTURE_ROWS) mod RING_SLOTS
                ld (top_slot),a
                ld hl,PICTURE_ROWS
                ld (cur_top_row),hl
                ret

;; ---------------------------------------------------------------------------
;; scroll_step - A = lines (0-8) the world moves down this game frame. On a
;; coarse step the new top row gets its slot; the caller draws it before the
;; next blit. Returns C on a coarse step.
;; ---------------------------------------------------------------------------
scroll_step:
                ld b,a
                ld a,(cur_j)
                sub b
                jr c,.coarse
                ld (cur_j),a
                ret                         ; (NC)
.coarse:        add a,ROW_LINES
                ld (cur_j),a
                ld hl,(cur_top_row)
                inc hl
                ld (cur_top_row),hl
                ld a,(top_slot)
                call slot_above
                ld (top_slot),a
                scf
                ret

cur_top_row:    defw 0              ; world row whose line cur_j is screen line 0
cur_j:          defb 0
top_slot:       defb 0              ; its slot in the ring
sync_timeouts:  defb 0              ; beam_sync gave up (no floating bus)
