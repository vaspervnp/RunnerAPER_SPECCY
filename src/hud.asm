; =============================================================================
; HUD: columns 24-31, beside the playfield (planzx.md 2.1).
;
; The CPC's HUD scrolled with its picture and had to be drawn again ahead of
; the beam every frame; here the blit never touches these columns, so an
; element is drawn only when what it shows changes (hud_update, after the
; game frame's logic). The same elements: the score, the best score (or this
; one when higher), the coins and lives, the route Kiato - Piraeus with the
; runner's place, the six power-ups (dark, or lit with their time left as a
; bar under them). A blue panel, and a railway down the right edge.
; =============================================================================

HUD_PANEL_ATTR  equ PAPER*BLUE+BRIGHT+WHITE
HUD_HI_ATTR     equ PAPER*BLUE+BRIGHT+YELLOW
HUD_OFF_ATTR    equ PAPER*BLUE+BLACK            ; a power-up not running
HUD_RAIL_ATTR   equ PAPER*BLACK+YELLOW
HUD_RAIL_COL    equ HUD_X+HUD_W-1
HUD_TITLE_ROW   equ 2
HUD_SCORE_ROW   equ 7
HUD_HI_ROW      equ 8
HUD_COINS_ROW   equ 10                  ; coins and lives
HUD_ROUTE_ROW   equ 11
HUD_PU_ROW      equ 13                  ; two rows of three, a bar under each
HUD_LABEL_ROW   equ 19                  ; PAUSE, DEMO
HUD_DIGITS_COL  equ HUD_X+1

; -----------------------------------------------------------------------------
; hud_init: the panel drawn, every element to be drawn by the next
; hud_update.
; -----------------------------------------------------------------------------
hud_init:
                ld c,0                      ; the panel, every row
.row:           ld b,HUD_X
                ld d,HUD_W-1
                ld e,HUD_PANEL_ATTR
                call clear_cells
                ld b,HUD_RAIL_COL           ; the railway
                call cell_addr
                ld de,gfx_hud_rail
                push hl
                ld b,8
.rail:          ld a,(de)
                ld (hl),a
                inc de
                inc h
                djnz .rail
                pop hl
                call cell_attr
                ld (hl),HUD_RAIL_ATTR
                inc c
                ld a,c
                cp 24
                jr c,.row
                ld a,HUD_HI_ATTR            ; the title
                ld (print_attr),a
                ld hl,hud_title
                ld bc,HUD_X*256+HUD_TITLE_ROW
                call draw_text
                ld hl,gfx_hud_coin          ; the coin and the lives' heart
                ld bc,HUD_X*256+HUD_COINS_ROW
                ld a,PAPER*BLUE+HUD_INK_COIN
                call hud_icon
                ld hl,gfx_hud_life
                ld bc,(HUD_X+5)*256+HUD_COINS_ROW
                ld a,PAPER*BLUE+HUD_INK_LIFE
                call hud_icon
                ld hl,hud_shown             ; nothing shown yet
                ld de,hud_shown+1
                ld bc,HUD_SHOWN_SIZE-1
                ld (hl),#FF
                ldir
                ret
hud_title:      defb GLYPH_A,GLYPH_DOT,GLYPH_P,GLYPH_DOT,GLYPH_E,GLYPH_DOT,GLYPH_R,TXT_END

; HL = an icon (8 bytes), B = column, C = row, A = its attribute
hud_icon:
                push af
                ex de,hl
                call cell_addr
                push hl
                ld b,8
.line:          ld a,(de)
                ld (hl),a
                inc de
                inc h
                djnz .line
                pop hl
                call cell_attr
                pop af
                ld (hl),a
                ret

; -----------------------------------------------------------------------------
; hud_refresh: every element drawn now (a new run: the menu's time).
; -----------------------------------------------------------------------------
hud_refresh:
                ld hl,hud_shown
                ld de,hud_shown+1
                ld bc,HUD_SHOWN_SIZE-1
                ld (hl),#FF
                ldir
                call hud_scores
                call hud_counts
                ld b,6
.pu:            push bc
                call hud_powerups
                pop bc
                djnz .pu
                ret

; -----------------------------------------------------------------------------
; hud_update: what changed since the last time drawn again: the scores one
; game frame, the rest the next.
; -----------------------------------------------------------------------------
hud_update:
                ld hl,hud_half
                ld a,(hl)
                xor 1
                ld (hl),a
                jr nz,hud_counts
hud_scores:
                ld a,HUD_PANEL_ATTR         ; the score
                ld (print_attr),a
                ld hl,score+2
                ld de,hud_shown+HS_SCORE+2
                ld bc,3*256+HUD_SCORE_ROW
                call hud_bcd
                ld hl,hiscore_table+2       ; the best: the table's first, or
                ld de,score+2               ; this score when higher
                ld b,3
.cmp:           ld a,(de)
                cp (hl)
                jr c,.table
                jr nz,.this
                dec hl
                dec de
                djnz .cmp
.table:         ld hl,hiscore_table+2
                jr .best
.this:          ld hl,score+2
.best:          ld a,HUD_HI_ATTR
                ld (print_attr),a
                ld de,hud_shown+HS_HI+2
                ld bc,3*256+HUD_HI_ROW
                jp hud_bcd
hud_counts:
                ld a,HUD_PANEL_ATTR         ; coins: 4 digits
                ld (print_attr),a
                ld hl,coins+1
                ld de,hud_shown+HS_COINS+1
                ld bc,2*256+HUD_COINS_ROW
                call hud_bcd
                ld a,(lives)                ; lives: a digit
                ld hl,hud_shown+HS_LIVES
                cp (hl)
                jr z,.lives_ok
                ld (hl),a
                add a,GLYPH_N0
                ld bc,(HUD_X+6)*256+HUD_COINS_ROW
                call draw_glyph
.lives_ok:      call route_pixel
                ld hl,hud_shown+HS_ROUTE
                cp (hl)
                jr z,.route_ok
                ld (hl),a
                call draw_route
.route_ok:      jp hud_powerups

; HL = the value's most significant BCD byte, DE = the shown copy's, B =
; bytes, C = row: the digits that changed, from HUD_DIGITS_COL on
hud_bcd:
                ld a,HUD_DIGITS_COL
                ld (.col),a
.byte:          ld a,(de)
                xor (hl)
                jr z,.same
                push af
                ld a,(hl)
                ld (de),a
                pop af
                push bc
                push de
                push hl
                and #F0                     ; the high digit changed?
                jr z,.low
                ld a,(hl)
                rrca
                rrca
                rrca
                rrca
                and 15
                add a,GLYPH_N0
                ld b,a
                ld a,(.col)
                ld h,b
                ld b,a
                ld a,h
                call draw_glyph
.low:           pop hl
                push hl
                ld a,(hl)
                and 15
                add a,GLYPH_N0
                ld b,a
                ld a,(.col)
                inc a
                ld h,b
                ld b,a
                ld a,h
                call draw_glyph
                pop hl
                pop de
                pop bc
.same:          ld a,(.col)
                add a,2
                ld (.col),a
                dec hl
                dec de
                djnz .byte
                ret
.col:           defb 0

; -----------------------------------------------------------------------------
; The route: seven stations (Kiato .. Piraeus) a cell apart, at the middle
; of each of the seven cells; the stretch run solid, the rest dotted, the
; runner a short bar.
; -----------------------------------------------------------------------------
ROUTE_X0        equ 4                   ; pixel of the first station
ROUTE_STEP_ROWS equ ROUTE_SEG/8         ; rows a pixel

; A = the runner's pixel on the route: 8 a station + rows into the stretch
route_pixel:
                ld hl,ROUTE_SEG
                ld de,(route_left)
                or a
                sbc hl,de                   ; HL = rows into this stretch
                ld de,ROUTE_STEP_ROWS
                ld b,-1
.div:           inc b
                or a
                sbc hl,de
                jr nc,.div
                ld a,(route_station)
                add a,a
                add a,a
                add a,a
                add a,b
                add a,ROUTE_X0
                ret

draw_route:
                ld (.px),a
                ld c,0                      ; C = cell
.cell:          ld a,(.px)                  ; A = the runner's pixel in it
                ld b,c
                inc b
                jr .in_test
.in:            sub 8
.in_test:       djnz .in
                ld e,0                      ; E = the solid track, D = marker
                ld d,e
                jp m,.masks                 ; (in a cell further on)
                cp 8
                jr c,.here
                ld e,#FF                    ; (in a cell before: all solid)
                jr .masks
.here:          ld b,a                      ; solid: the first sx+1 pixels;
                inc b                       ; marker: pixel sx
                ld d,#80
                scf
                rr e
                jr .bit_test
.bits:          scf
                rr e
                srl d
.bit_test:      djnz .bits
.masks:         ld a,e                      ; the track: solid, else dotted
                cpl
                and #AA
                or e
                ld e,a
                ld a,c                      ; from the first station to the
                or a                        ; last only
                jr nz,.not_first
                ld a,e
                and #0F
                ld e,a
.not_first:     ld a,c
                cp 6
                jr nz,.not_last
                ld a,e
                and #F8
                ld e,a
.not_last:      push bc
                ld a,c
                add a,HUD_X
                ld b,a
                ld c,HUD_ROUTE_ROW
                call cell_addr
                ld (hl),d                   ; 0: the marker
                inc h
                ld a,d                      ; 1: the station
                or #08
                ld (hl),a
                inc h
                ld (hl),d                   ; 2
                inc h
                ld a,d                      ; 3, 4: the track
                or e
                ld (hl),a
                inc h
                ld (hl),a
                inc h
                ld (hl),d                   ; 5, 6
                inc h
                ld (hl),d
                inc h
                ld (hl),0                   ; 7
                ld a,h
                sub 7
                ld h,a
                call cell_attr
                ld (hl),HUD_PANEL_ATTR
                pop bc
                inc c
                ld a,c
                cp 7
                jr nz,.cell
                ret
.px:            defb 0

; -----------------------------------------------------------------------------
; The power-ups: an icon each, lit while it runs (dark otherwise), and under
; it its time left, a pixel for so many frames (the CPC's), up to 8.
; -----------------------------------------------------------------------------
PU_HUD_SIZE     equ 6                   ; timer, frames a pixel, icon, ink
hud_powerups:                               ; (one a frame, in turn)
                ld a,(hud_pu_next)
                inc a
                cp 6
                jr c,.which
                xor a
.which:         ld (hud_pu_next),a
                ld c,a
                ld b,a
                ld ix,pu_hud_table-PU_HUD_SIZE
                ld de,PU_HUD_SIZE
                inc b
.find:          add ix,de
                djnz .find
                ld hl,hud_shown+HS_PU
                ld a,c
                call add_a_hl
                push hl
                pop iy
.pu:            push bc
                ld l,(ix+0)                 ; its timer
                ld h,(ix+1)
                ld a,h
                or l
                jr nz,.timed
                ld a,(helmet)               ; no timer: the helmet
                or a
                jr z,.state
                ld a,#80                    ; on, no bar
                jr .state
.timed:         ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a                      ; HL = frames left
                or h
                jr z,.state                 ; (A = 0: off)
                ld e,(ix+2)                 ; pixels = ceil(frames / step)
                ld d,0
                ld b,0
.count:         inc b
                or a
                sbc hl,de
                jr z,.counted
                jr nc,.count
.counted:       ld a,b
                cp 9
                jr c,.px
                ld a,8
.px:            or #80
.state:         pop bc
                cp (iy+0)                   ; changed?
                ret z
                ld (iy+0),a
                jp hud_pu_draw

; IX = its table entry, C = which (0-5), A = state (bit 7 on, bits 0-3 the
; bar's pixels): its icon and bar
hud_pu_draw:
                ld (.state),a
                ld a,c                      ; column 25, 27, 29; rows 13, 15
                ld b,HUD_PU_ROW
                cp 3
                jr c,.row
                sub 3
                ld b,HUD_PU_ROW+2
.row:           add a,a
                add a,HUD_X+1
                ld c,b
                ld b,a                      ; B = column, C = row
                ld l,(ix+3)
                ld h,(ix+4)
                ld a,(.state)
                or a
                ld a,HUD_OFF_ATTR
                jp p,.icon
                ld a,(ix+5)
                or PAPER*BLUE
.icon:          push bc
                call hud_icon
                pop bc
                inc c                       ; the bar under it, lines 1-2
                call cell_addr
                ld a,(.state)
                and 15
                ld b,a
                xor a
                inc b
                jr .bar_test
.bar:           scf
                rra
.bar_test:      djnz .bar
                inc h
                ld (hl),a
                inc h
                ld (hl),a
                ret
.state:         defb 0

pu_hud_table:   defw pu_magnet
                defb 32
                defw gfx_hud_magnet
                defb HUD_INK_MAGNET
                defw pu_turbo
                defb 25
                defw gfx_hud_turbo
                defb HUD_INK_TURBO
                defw pu_slow
                defb 25
                defw gfx_hud_slow
                defb HUD_INK_SLOW
                defw 0                      ; the helmet (no timer)
                defb 0
                defw gfx_hud_helmet
                defb HUD_INK_HELMET
                defw pu_spring
                defb 32
                defw gfx_hud_spring
                defb HUD_INK_SPRING
                defw pu_ticket
                defb 47
                defw gfx_hud_ticket
                defb HUD_INK_TICKET

; -----------------------------------------------------------------------------
; hud_label: HL = text (or 0: none), in the panel's label row
; -----------------------------------------------------------------------------
hud_label:
                push hl
                ld bc,HUD_X*256+HUD_LABEL_ROW
                ld de,(HUD_W-1)*256+HUD_PANEL_ATTR
                call clear_cells
                pop hl
                ld a,h
                or l
                ret z
                ld a,HUD_HI_ATTR
                ld (print_attr),a
                call text_len               ; centred in the panel
                neg
                add a,HUD_W-1
                srl a
                add a,HUD_X
                ld b,a
                ld c,HUD_LABEL_ROW
                jp draw_text

; what the HUD shows (#FF: to be drawn)
HS_SCORE        equ 0                   ; 3
HS_HI           equ 3                   ; 3
HS_COINS        equ 6                   ; 2
HS_LIVES        equ 8
HS_ROUTE        equ 9
HS_PU           equ 10                  ; 6
HUD_SHOWN_SIZE  equ 16
hud_shown:      defs HUD_SHOWN_SIZE
hud_pu_next:    defb 0                  ; the power-up looked at last
hud_half:       defb 0                  ; hud_update: which half
