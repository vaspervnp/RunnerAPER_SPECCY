; =============================================================================
; Text: the font on the screen (menus, HUD) and names on the track.
;
; A text is a string of glyph indices ending in TXT_END (tools/mktext.py,
; src/data/text.asm); each glyph is a cell, 8 bytes (gfx_font). On the
; screen it goes at a character cell with the attribute in print_attr.
;
; Names on the track (a power-up's, a station's, the countdown): the CPC
; wrote them once into its picture and they scrolled away with it. Here they
; go into the ring the same way, over a whole world row (so its cells take
; the label's colours and nothing else), white on black, centred on the
; playfield: make_label notes it at the pickup, and over the next frames
; label_frame builds the picture in label_buf (in a tile's form) and puts it
; into the row with blit_tile. show_label does both at once (the countdown:
; the world stands still).
; =============================================================================

LABEL_ROW       equ 8                   ; picture row a name goes into
LABEL_ATTR      equ BRIGHT+PAPER*BLACK+WHITE
COUNT_ROW       equ LABEL_ROW+3         ; the countdown's numbers

; -----------------------------------------------------------------------------
; draw_text: HL = text, B = column, C = character row, attribute print_attr.
; Destroys AF, BC, DE, HL.
; -----------------------------------------------------------------------------
draw_text:
.glyph:         ld a,(hl)
                cp TXT_END
                ret z
                push hl
                call draw_glyph
                pop hl
                inc hl
                inc b
                jr .glyph

; A = glyph, B = column, C = character row: the glyph and print_attr there.
; Keeps BC.
draw_glyph:
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld de,gfx_font
                add hl,de
                ex de,hl                    ; DE = the glyph
                call cell_addr              ; HL = the cell's first line
                push hl
                ld a,8
.line:          ex af,af'
                ld a,(de)
                ld (hl),a
                inc de
                inc h
                ex af,af'
                dec a
                jr nz,.line
                pop hl
                call cell_attr              ; its attribute
                ld a,(print_attr)
                ld (hl),a
                ret

; B = column, C = character row -> HL = the cell's first screen byte
cell_addr:
                ld a,c
                and #18
                or SCR_BITMAP>>8
                ld h,a
                ld a,c
                and 7
                rrca
                rrca
                rrca
                or b
                ld l,a
                ret

; HL = a cell's first screen byte -> HL = its attribute
cell_attr:
                ld a,h
                rrca
                rrca
                rrca
                and 3
                or SCR_ATTR>>8
                ld h,a
                ret

; HL = text, C = character row: centred on the playfield
draw_text_centred:
                call text_len
                neg
                add a,PLAY_W
                srl a
                ld b,a
                jr draw_text

; HL = text -> A = its length. Keeps HL.
text_len:
                push hl
                ld b,0
.count:         ld a,(hl)
                cp TXT_END
                jr z,.counted
                inc b
                inc hl
                jr .count
.counted:       ld a,b
                pop hl
                ret

; B = column, C = character row, D = cells, E = attribute: those cells
; blank, in that attribute. Destroys AF, B, D, HL.
clear_cells:
.cell:          push de
                call cell_addr
                push hl
                xor a
                ld e,8
.line:          ld (hl),a
                inc h
                dec e
                jr nz,.line
                pop hl
                call cell_attr
                pop de
                ld (hl),e
                inc b
                dec d
                jr nz,.cell
                ret

; DE = most significant BCD byte, B = bytes, HL = text position: 2B digit
; glyphs (HL moves on)
bcd_text:
.byte:          ld a,(de)
                rrca
                rrca
                rrca
                rrca
                and 15
                add a,GLYPH_N0
                ld (hl),a
                inc hl
                ld a,(de)
                and 15
                add a,GLYPH_N0
                ld (hl),a
                inc hl
                dec de
                djnz .byte
                ret

; HL = 0-65535 -> text_buf: 5 digits, TXT_END
dec_text:
                ld de,text_buf
                ld bc,-10000
                call .digit
                ld bc,-1000
                call .digit
                ld bc,-100
                call .digit
                ld bc,-10
                call .digit
                ld bc,-1
                call .digit
                ld a,TXT_END
                ld (de),a
                ret
.digit:         ld a,GLYPH_N0-1
.sub:           inc a
                add hl,bc
                jr c,.sub
                sbc hl,bc
                ld (de),a
                inc de
                ret

; -----------------------------------------------------------------------------
; Names on the track
; -----------------------------------------------------------------------------
; make_label: A = label (2-7 a power-up, LABEL_*): its name over the world
; row now at LABEL_ROW, over the next two frames (label_frame).
make_label:
                ld (label_item),a
                ld hl,(cur_top_row)
                ld de,LABEL_ROW
                or a
                sbc hl,de
                ld (label_at),hl
                ld a,1
                ld (label_wait),a
                ret

; label_frame: after the game frame's logic: 1 builds the picture, 2 puts
; it into its row (still in the picture: it moves down a row or two at most).
label_frame:
                ld a,(label_wait)
                or a
                ret z
                dec a
                jr nz,.put
                ld a,2
                ld (label_wait),a
                jr build_label
.put:           xor a
                ld (label_wait),a
                jr put_label

; A = label, C = picture row: its name there at once
show_label:
                ld (label_item),a
                ld e,c
                ld d,0
                ld hl,(cur_top_row)
                or a
                sbc hl,de
                ld (label_at),hl
                call build_label
                ; fall through

; label_buf into row label_at, centred on the playfield
put_label:
                ld hl,(label_at)           ; its slot: the top's, a slot on
                ld de,(cur_top_row)         ; for each row below
                ex de,hl
                or a
                sbc hl,de                   ; HL = picture row
                ld a,h
                or a
                ret nz                      ; (gone: never)
                ld a,l
                cp PICTURE_ROWS+1
                ret nc
                ld b,a
                ld a,(top_slot)
                inc b
                jr .test
.down:          call slot_below
.test:          djnz .down
                ld (rr_slot),a
                call slot_addr
                ld (rr_dest),hl
                ld a,(rr_slot)
                call attr_slot_addr
                ld (rr_attr),hl
                xor a                       ; (rr_* are no longer render_part's)
                ld (rr_mine),a
                ld hl,(label_at)            ; (its descriptor: written over, for
                call desc_addr              ; the tests)
                set 5,(hl)                  ; F_LABEL
                ld a,(label_w)              ; centred
                ld c,a
                neg
                add a,PLAY_W
                srl a
                ld b,a
                ld hl,label_buf
                call blit_tile
                ld a,(rr_slot)              ; (the attributes' second copy)
                call ring_done
                ld a,1                      ; the blit: write them again
                ld (attr_dirty),a
                ret

; label_item's name -> label_buf: 8 lines of label_w bytes, then label_w
; attributes (a tile, for blit_tile), a blank cell either side
build_label:
                ld a,(label_item)
                sub 2
                add a,a
                ld hl,txt_pu_magnet         ; (the labels' texts in order)
                call add_a_hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a                      ; HL = the text
                call text_len               ; width: a blank cell either
                ld e,a                      ; side, as far as there is room
                add a,2
                cp PLAY_W+1
                jr c,.width
                ld a,PLAY_W
.width:         ld (label_w),a
                sub e
                srl a
                ld (.first),a               ; the first glyph's column
                ld a,(label_w)
                ld e,a
                ld d,0                      ; DE = width
                push hl
                ld hl,label_buf             ; the first and last columns
                ld b,8                      ; blank (the glyphs cover the
.clear:         ld (hl),0                   ; rest), the attributes after
                push hl
                add hl,de
                dec hl
                ld (hl),0
                pop hl
                add hl,de
                djnz .clear
                ld b,e
.attr:          ld (hl),LABEL_ATTR
                inc hl
                djnz .attr
                pop hl
                ld de,label_buf             ; DE = the first glyph's column
                ld a,(.first)
                add a,e
                ld e,a
                jr nc,.glyph
                inc d
.glyph:         ld a,(hl)
                cp TXT_END
                ret z
                push hl
                push de
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld bc,gfx_font
                add hl,bc                   ; HL = the glyph
                ld a,(label_w)
                ld c,a
                ld b,8
.line:          ld a,(hl)
                ld (de),a
                inc hl
                ld a,e
                add a,c
                ld e,a
                jr nc,.nc
                inc d
.nc:            djnz .line
                pop de
                inc de
                pop hl
                inc hl
                jr .glyph
.first:         defb 0

label_item:     defb 0
label_at:      defw 0                  ; the world row it goes into
label_wait:     defb 0                  ; label_frame: 1 build, 2 put
label_w:        defb 0
print_attr:      defb BRIGHT+WHITE
text_buf:       defs PLAY_W+1               ; a text put together (scores)
label_buf:      defs 8*PLAY_W+PLAY_W        ; build_label's tile
