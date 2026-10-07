; =============================================================================
; Sprites, drawn on the screen by the blit (planzx.md 2.2).
;
; The runner, his shadow and the coins the magnet pulls go on the screen in
; the middle of the blit: as soon as it has copied a character row of the
; picture, the lines of the sprites that fall in that row are drawn over it.
; The beam of the game frame's first TV frame has long passed that row, the
; second's is far from it, so they are never seen half drawn; and nothing
; under them is saved, because the next blit writes the whole row again.
;
; sprite_add fills a slot before the blit, which then calls sprites_row for
; every character row marked in spr_rowmark. A slot follows its sprite
; down: its next screen line, the lines it has left, where that line's data
; is. Lines of a bridge deck's rows are left out for the runner and his
; shadow (they pass under it, as on the CPC); a bridge's shadow row is not a
; deck.
;
; A sprite: width (bytes), height (lines), ink (unused here: a sprite takes
; the ink of the cells it is in), then each line as a span: the bytes to
; skip, how many are drawn, and those as (mask, data) pairs.
; =============================================================================

SPRITES         equ 5                   ; runner, shadow, three coins
SP_LINES        equ 0                   ; lines left (0: free)
SP_Y            equ 1                   ; its next screen line
SP_COL          equ 2                   ; byte column
SP_CLIP         equ 3                   ; 1: hidden under bridge decks
SP_DATA         equ 4                   ; (2) its next line's span
SP_SIZE         equ 6

; -----------------------------------------------------------------------------
; sprites_clear: no sprites this frame. Destroys AF, B, HL.
; -----------------------------------------------------------------------------
sprites_clear:
                xor a
                ld (spr_count),a
                ld hl,spr_stamp             ; (the rows' marks: stale)
                inc (hl)
                jp nz,decks_near
                inc (hl)                    ; round to 0: none may match the
                ld hl,spr_rowmark           ; marks of 256 frames ago
                ld b,PICTURE_ROWS
.unmark:        ld (hl),a
                inc hl
                djnz .unmark
                jp decks_near

; -----------------------------------------------------------------------------
; sprite_add: IX = sprite, L = its top screen line, C = byte column, B = 1 to
; hide it under bridge decks. Lines below the picture are left out; a sprite
; with no slot left is not drawn. Destroys AF, BC, DE, HL, IY.
; -----------------------------------------------------------------------------
sprite_add:
                ld a,l
                cp PLAY_LINES
                ret nc
                ld a,(spr_count)            ; the next slot
                cp SPRITES
                ret nc
                inc a
                ld (spr_count),a
                dec a
                ld iy,spr_slots
                ld de,SP_SIZE
                inc a
                jr .slot_test
.slot:          add iy,de
.slot_test:     dec a
                jr nz,.slot
                ld a,l
                ld (iy+SP_Y),a
                ld (iy+SP_COL),c
                ld (iy+SP_CLIP),b
                ld a,(ix+1)                 ; its lines, those on the screen
                ld b,a
                add a,l
                sub PLAY_LINES
                jr c,.lines
                neg
                add a,b
                ld b,a
.lines:         ld (iy+SP_LINES),b
                push ix
                pop de
                inc de
                inc de
                inc de
                ld (iy+SP_DATA),e
                ld (iy+SP_DATA+1),d
                ld a,l                      ; its character rows marked
                rrca
                rrca
                rrca
                and 31
                ld c,a                      ; C = first
                ld a,l
                add a,b
                dec a
                rrca
                rrca
                rrca
                and 31
                sub c
                inc a
                ld b,a                      ; B = how many
                ld a,c
                ld hl,spr_rowmark
                call add_a_hl
                ld a,(spr_stamp)
.mark:          ld (hl),a                   ; (none below the picture: the
                inc hl                      ; lines were cut to it)
                djnz .mark
                ret

; -----------------------------------------------------------------------------
; sprites_row: A = character row of the screen, just copied by the blit: the
; lines of every sprite that fall in it, each sprite's from one address down
; (INC H), its spans read with POP (the blit has interrupts off). A line in
; a bridge deck's row is hidden for the sprites that go under them: which of
; the character row's eight lines are, sr_deck says (bit 0 = its first).
; Destroys everything (the blit loads its registers again after).
; -----------------------------------------------------------------------------
sprites_row:
                ld (sr_row),a
                ld a,(spr_count)
                or a
                ret z
                ld a,(sr_row)
                ld c,a
                add a,a
                add a,a
                add a,a
                add a,7
                ld (sr_last),a              ; its last line
                ld a,c                      ; its first line's address, column 0
                and #18
                or SCR_BITMAP>>8
                ld (sr_high),a
                ld a,c
                and 7
                rrca
                rrca
                rrca
                ld (sr_low),a
                xor a
                ld (sr_deck_ok),a
                ld (sr_sp),sp
                ld ix,spr_slots
                ld a,(spr_count)
.slot:          ld (sr_left),a
                ld a,(ix+SP_LINES)
                or a
                jp z,.next
                ld c,a                      ; C = its lines left
                ld a,(sr_last)
                sub (ix+SP_Y)
                jp c,.next                  ; it starts further down
                inc a                       ; lines of it in this row
                cp c
                jr c,.n
                ld a,c
.n:             ld iyh,a                    ; IYH = lines to draw
                ld b,a
                ld a,c
                sub b
                ld (ix+SP_LINES),a
                ld a,(ix+SP_Y)
                ld c,a
                add a,b
                ld (ix+SP_Y),a
                ld a,c                      ; its first line in the row, 0-7
                and 7
                ld c,a
                ld a,(spr_clip)             ; a deck near and it goes under:
                and (ix+SP_CLIP)            ; the mask of its lines
                ld (sr_clip),a
                call nz,clip_mask
                ld a,(sr_low)
                add a,(ix+SP_COL)
                ld iyl,a                    ; IYL = the sprite's column
                ld a,(sr_high)
                or c
                ld d,a                      ; D = H of its first line
                ld l,(ix+SP_DATA)
                ld h,(ix+SP_DATA+1)
                ld sp,hl
                ld h,d
                ld a,(sr_clip)
                or a
                jr nz,.clipped
.line:          pop bc                      ; C = skip, B = count
                ld a,iyl
                add a,c
                ld l,a
                inc b
                dec b
                jr z,.done_line
.byte:          pop de                      ; E = mask, D = data
                ld a,(hl)
                and e
                or d
                ld (hl),a
                inc l
                djnz .byte
.done_line:     inc h
                dec iyh
                jr nz,.line
.sprite_done:   ld hl,0                     ; where its next line is
                add hl,sp
                ld (ix+SP_DATA),l
                ld (ix+SP_DATA+1),h
                ld sp,(sr_sp)
.next:          ld de,SP_SIZE
                add ix,de
                ld a,(sr_left)
                dec a
                jp nz,.slot
                ret
.clipped:       pop bc                      ; the same, a line in a deck's
                ld a,iyl                    ; row passed over
                add a,c
                ld l,a
                ld a,(sr_mask)
                rrca
                ld (sr_mask),a
                jr c,.hidden
                inc b
                dec b
                jr z,.clip_next
.clip_byte:     pop de
                ld a,(hl)
                and e
                or d
                ld (hl),a
                inc l
                djnz .clip_byte
.clip_next:     inc h
                dec iyh
                jr nz,.clipped
                jr .sprite_done
.hidden:        inc b
                dec b
                jr z,.clip_next
.pass:          pop de
                djnz .pass
                jr .clip_next

; clip_mask: C = the sprite's first line in the character row (0-7):
; sr_mask = sr_deck from that line on. sr_deck is worked out for the first
; sprite that needs it. Destroys AF, B, DE, HL.
clip_mask:
                ld a,(sr_deck_ok)
                or a
                call z,deck_lines
                ld hl,.rotated              ; C RRCAs
                ld a,l
                sub c
                ld l,a
                jr nc,.go
                dec h
.go:            ld a,(sr_deck)
                jp (hl)
                rrca
                rrca
                rrca
                rrca
                rrca
                rrca
                rrca
.rotated:       ld (sr_mask),a
                ret

; sr_deck for the character row sr_row: a line is a deck's if the picture
; row it shows is one (deck_flags, worked out before the blit). Of the eight
; lines, the first 8 - j show picture row sr_row, the others the next one.
; Destroys AF, DE, HL.
deck_lines:
                ld a,(sr_row)
                sub CLIP_FIRST_ROW
                ld de,0
                jr nc,.table
                inc a                       ; above the first: only the row
                jr nz,.flags                ; just above it shows a deck's
                ld a,(deck_flags)           ; lines, in its last ones
                ld d,a
                jr .flags
.table:         ld hl,deck_flags
                add a,l
                ld l,a
                jr nc,.at
                inc h
.at:            ld e,(hl)                   ; E = its row's, D = the next's
                inc hl
                ld d,(hl)
.flags:         ld a,(sr_jmask)             ; #FF >> j
                and e
                ld e,a
                ld a,(sr_jmask)
                cpl
                and d
                or e
                ld (sr_deck),a
                ld a,1
                ld (sr_deck_ok),a
                ret

; A = picture row (0 = the top row): A = 1 if it is a bridge deck (its shadow
; row is not), else 0. Destroys F, DE, HL.
deck_row:
                ld e,a
                ld d,0
                ld hl,(cur_top_row)
                or a
                sbc hl,de
                call desc_addr
                xor a
                bit 7,(hl)                  ; F_BRIDGE
                ret z
                inc hl
                ld a,(hl)
                cp IDX_BRIDGES_FOOTBRIDGE_SHADOW
                ld a,0
                ret z
                ld a,(hl)
                cp IDX_BRIDGES_ROADBRIDGE_SHADOW
                ld a,0
                ret z
                inc a
                ret

; -----------------------------------------------------------------------------
; decks_near: spr_clip = 1 if any picture row from CLIP_FIRST_ROW down is a
; bridge deck, so that only then the runner's lines are looked at one by one.
; -----------------------------------------------------------------------------
CLIP_FIRST_ROW  equ 16                  ; the runner's top: line 128 at least
DECK_ROWS       equ PICTURE_ROWS+2-CLIP_FIRST_ROW
decks_near:
                ld hl,(cur_top_row)         ; the picture moved on a row: the
                ld de,(dn_top)              ; flags move down one, and only
                ld (dn_top),hl              ; the new row is looked at
                or a
                sbc hl,de
                jr z,.clip                  ; (not at all: as they were)
                dec hl
                ld a,h
                or l
                jr nz,.all
                ld hl,deck_flags+DECK_ROWS-2
                ld de,deck_flags+DECK_ROWS-1
                ld bc,DECK_ROWS-1
                lddr
                ld a,CLIP_FIRST_ROW
                call deck_row
                neg
                ld (deck_flags),a
                jr .clip
.all:           ld hl,deck_flags
                ld c,CLIP_FIRST_ROW
.row:           push hl
                ld a,c
                call deck_row
                pop hl
                neg                         ; 0 / #FF
                ld (hl),a
                inc hl
                inc c
                ld a,c
                cp PICTURE_ROWS+2
                jr c,.row
.clip:          ld hl,deck_flags            ; any of them a deck?
                ld b,DECK_ROWS
                xor a
.or:            or (hl)
                inc hl
                djnz .or
                and 1
                ld (spr_clip),a
                ld a,(cur_j)                ; #FF >> j, for deck_lines
                ld b,a
                ld a,#FF
                inc b
                jr .shift_test
.shift:         srl a
.shift_test:    djnz .shift
                ld (sr_jmask),a
                ret

spr_slots:      defs SPRITES*SP_SIZE
spr_count:      defb 0                  ; slots used this frame
deck_flags:     defs DECK_ROWS          ; #FF: picture row CLIP_FIRST_ROW + n a deck
sr_jmask:       defb 0
spr_rowmark:    defs PICTURE_ROWS           ; spr_stamp: the row has sprite lines
spr_stamp:      defb 0
dn_top:         defw #FFFF              ; cur_top_row deck_flags are for
sr_last:        defb 0
sr_high:        defb 0
sr_low:         defb 0
sr_clip:        defb 0
sr_sp:          defw 0
sr_row:         defb 0
sr_deck_ok:     defb 0
sr_left:        defb 0
sr_deck:        defb 0                  ; the character row's lines in a deck
sr_mask:        defb 0                  ; the same, from the sprite's next line
spr_clip:       defb 0                  ; a deck in the runner's rows (decks_near)
