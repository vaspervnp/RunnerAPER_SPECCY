;; ===========================================================================
;; m1.asm - milestone 1 on a tape of its own: the scroll engine (planzx.md
;; 2.2). A test world - every row its own diagonal stripes, its top line
;; solid, its colour from its number - scrolled down m1_speed lines a game
;; frame through the ring and the blit that chases the beam. tools/
;; beamcheck.py watches every byte it writes to the screen.
;; ===========================================================================

                include "config.asm"

                org CODE_ORG
m1_start:
                di
                ld sp,STACK_TOP
                call screen_clear
                call irq_init
                call scroll_init
                ld hl,0                     ; rows 0 .. PICTURE_ROWS
                xor a                       ; slot of row 0
.init:          push hl
                push af
                call test_row
                pop af
                pop hl
                call slot_above
                inc hl
                ld e,a
                ld a,l
                cp PICTURE_ROWS+1
                ld a,e
                jr nz,.init

m1_loop:
                call wait_game_frame
                call beam_sync
                call blit
m1_after_blit:
                ld a,(m1_speed)
                call scroll_step
                jr nc,m1_loop
                ld hl,(cur_top_row)         ; a coarse step: the new top row
                ld a,(top_slot)
                call test_row
                jr m1_loop

m1_speed:       defb 4

;; ---------------------------------------------------------------------------
;; test_row - HL = world row, A = its slot: its pixels and attributes.
;; ---------------------------------------------------------------------------
test_row:
                ld (tr_row),hl
                push af
                call slot_addr
                ld b,PLAY_W                 ; line 0: solid
.top:           ld (hl),#FF
                inc hl
                djnz .top
                ld c,1                      ; lines 1-7: a diagonal stripe,
.line:          ld a,(tr_row)               ; bit (row*8 + 7 - line + col) & 7
                add a,a
                add a,a
                add a,a
                sub c
                add a,7
                                            ; (an even ring line starts at
                                            ; column 8: the same bit)
                ld e,a                      ; E = the line in the world + column
                ld d,stripe>>8
                ld b,PLAY_W
.col:           ld a,e
                and 7
                or stripe&255
                push de
                ld e,a
                ld a,(de)
                pop de
                ld (hl),a
                inc hl
                inc e
                djnz .col
                inc c
                ld a,c
                cp ROW_LINES
                jr nz,.line
                pop af
                push af
                call attr_slot_addr         ; ink 1-7 by the row number
                ld a,(tr_row)
.mod7:          sub 7
                jr nc,.mod7
                add a,8                     ; 1..7
                ld b,PLAY_W
.attr:          ld (hl),a
                inc hl
                djnz .attr
                pop af
                jp ring_done
tr_row:         defw 0
                align 8
stripe:         defb #80,#40,#20,#10,#08,#04,#02,#01

;; ---------------------------------------------------------------------------
;; screen_clear - black playfield, a blue HUD.
;; ---------------------------------------------------------------------------
screen_clear:
                ld hl,SCR_BITMAP
                ld de,SCR_BITMAP+1
                ld bc,SCR_LINES*32-1
                ld (hl),0
                ldir
                ld hl,SCR_ATTR
                ld b,PICTURE_ROWS
.row:           ld c,PLAY_W
.play:          ld (hl),WHITE
                inc hl
                dec c
                jr nz,.play
                ld c,HUD_W
.hud:           ld (hl),PAPER*BLUE+WHITE
                inc hl
                dec c
                jr nz,.hud
                djnz .row
                xor a
                out (#FE),a
                ret

                include "irq.asm"
                include "video.asm"

; no sprites here: rows never marked (src/sprite.asm)
spr_rowmark:    defs PICTURE_ROWS
spr_stamp:      defb 1
sprites_row:    ret

m1_end:
                assert m1_end <= CODE_LIMIT
LOAD_ADDR       equ m1_start
LOAD_CLEAR      equ CODE_ORG-1
BIN_ORG         equ CODE_ORG            ; where the saved block goes
                save "build/m1.bin",CODE_ORG,m1_end-CODE_ORG
