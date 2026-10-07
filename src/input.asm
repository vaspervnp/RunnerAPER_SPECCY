; =============================================================================
; Keyboard and joysticks (planzx.md 4, M4).
;
; keys_held    - controls held now (1 = down)
; keys_pressed - controls that went down since the previous read
; matrix       - the eight half-rows as read (1 = down), for the keys a
;                screen looks at itself (L, M)
;
; The CPC's control bits, so the game reads them as it did there:
;   left  = O, Sinclair 6, Kempston left        right = P, Sinclair 7, Kempston right
;   jump  = Q, SPACE, ENTER, Sinclair 9 and 0, Kempston up and fire
;   (menus: up = Q, Sinclair 9, Kempston up; select = SPACE, ENTER, fire)
;   down  = A, Sinclair 8, Kempston down        pause = H
;   esc   = BREAK (CAPS SHIFT + SPACE), which is then not a jump
;
; A Kempston is believed in only if port #1F read like one for two whole
; frames at boot (kempston_detect, after the Loukoumas port): with no
; interface the port is the floating bus, which sooner or later has one of
; bits 5-7 set.
; =============================================================================

KEY_LEFT        equ 1
KEY_RIGHT       equ 2
KEY_JUMP        equ 4
KEY_DOWN        equ 8
KEY_PAUSE       equ 16
KEY_ESC         equ 32
KEY_UP          equ 64                  ; menus: up (also a jump in the game)
KEY_FIRE        equ 128                 ; menus: select (also a jump in the game)

; half-rows by their place in matrix (port #xxFE, high byte #FE, #FD .. #7F)
ROW_CAPS        equ 0                   ; CAPS Z X C V
ROW_A           equ 1                   ; A S D F G
ROW_Q           equ 2                   ; Q W E R T
ROW_1           equ 3                   ; 1 2 3 4 5
ROW_0           equ 4                   ; 0 9 8 7 6
ROW_P           equ 5                   ; P O I U Y
ROW_ENTER       equ 6                   ; ENTER L K J H
ROW_SPACE       equ 7                   ; SPACE SYM M N B

; key -> control: half-row, bit mask (1 = key), control bits. Unrolled into
; read_input.
macro KEY row,mask,bits
                ld a,(matrix+{row})
                and {mask}
                jr z,@skip
                ld a,c
                or {bits}
                ld c,a
@skip:
mend

; -----------------------------------------------------------------------------
; read_input: updates keys_held / keys_pressed. Destroys A, BC, DE, HL.
; -----------------------------------------------------------------------------
read_input:
                ld hl,matrix
                ld b,#FE
.row:           ld c,#FE
                in a,(c)
                cpl
                and #1F
                ld (hl),a
                inc hl
                rlc b
                jr c,.row
                ld c,0
                ld a,(matrix+ROW_CAPS)      ; BREAK: CAPS SHIFT and SPACE
                and 1
                jr z,.no_break
                ld a,(matrix+ROW_SPACE)
                and 1
                jr z,.no_break
                ld c,KEY_ESC
                ld hl,matrix+ROW_SPACE      ; (and the SPACE is not a jump)
                res 0,(hl)
.no_break:
                KEY ROW_P,%00010,KEY_LEFT           ; O
                KEY ROW_P,%00001,KEY_RIGHT          ; P
                KEY ROW_Q,%00001,KEY_JUMP|KEY_UP    ; Q
                KEY ROW_A,%00001,KEY_DOWN           ; A
                KEY ROW_SPACE,%00001,KEY_JUMP|KEY_FIRE  ; SPACE
                KEY ROW_ENTER,%00001,KEY_JUMP|KEY_FIRE  ; ENTER
                KEY ROW_ENTER,%10000,KEY_PAUSE      ; H
                KEY ROW_0,%10000,KEY_LEFT           ; 6: Sinclair left
                KEY ROW_0,%01000,KEY_RIGHT          ; 7: right
                KEY ROW_0,%00100,KEY_DOWN           ; 8: down
                KEY ROW_0,%00010,KEY_JUMP|KEY_UP    ; 9: up
                KEY ROW_0,%00001,KEY_JUMP|KEY_FIRE  ; 0: fire
                ld a,(kempston_on)
                or a
                jr z,.edges
                in a,(#1F)                  ; Kempston: fire up down left right
                ld b,a
                rra
                jr nc,.k_left
                set 1,c                     ; KEY_RIGHT
.k_left:        rra
                jr nc,.k_down
                set 0,c                     ; KEY_LEFT
.k_down:        rra
                jr nc,.k_up
                set 3,c                     ; KEY_DOWN
.k_up:          rra
                jr nc,.k_fire
                ld a,c
                or KEY_JUMP|KEY_UP
                ld c,a
.k_fire:        bit 4,b
                jr z,.edges
                ld a,c
                or KEY_JUMP|KEY_FIRE
                ld c,a
.edges:         ld a,(keys_held)            ; pressed = now AND NOT before
                cpl
                and c
                ld (keys_pressed),a
                ld a,c
                ld (keys_held),a
                ret

; -----------------------------------------------------------------------------
; kempston_detect: kempston_on = 1 if port #1F read like a joystick (none of
; bits 5-7) for two whole frames. Interrupts on. Destroys AF, BC, HL.
; -----------------------------------------------------------------------------
kempston_detect:
                halt                        ; from the top of a frame
                ld a,(frame_count)
                add a,2
                ld l,a
                ld h,0                      ; H = all the reads ORed
.listen:        in a,(#1F)
                or h
                ld h,a
                ld a,(frame_count)
                cp l
                jr nz,.listen
                ld a,h
                and #E0
                ld a,1
                jr z,.on
                xor a
.on:            ld (kempston_on),a
                ret

matrix:         defs 8
keys_held:      defb 0
keys_pressed:   defb 0
kempston_on:    defb 0
