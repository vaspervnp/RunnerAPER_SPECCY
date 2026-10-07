;; ===========================================================================
;; config.asm - the machine, the screen, the layout and the memory map.
;;
;; One file holds every number the rest derives from (planzx.md sections 2.1
;; to 2.5). Sizes across the screen are in bytes - eight pixels - so the lane
;; centres, the lane changes and the scenery all fall on byte boundaries and
;; nothing needs pre-shifting.
;;
;; rasm works expressions out in floating point and rounds the result: an
;; integer division says so with >> or floor().
;; ===========================================================================

;; --- The frame --------------------------------------------------------------
;; The 48K: 312 lines of 224 T, the interrupt at T 0, line 0 of the picture
;; fetched from T 14336. The 128K's lines are 228 T and its frame 70908 T;
;; nothing below depends on the exact number.
T_PER_LINE      equ 224
FRAME_LINES     equ 312
T_PER_FRAME     equ T_PER_LINE*FRAME_LINES      ; 69888
T_TO_PICTURE    equ 64*T_PER_LINE               ; 14336
TV_PER_GAME     equ 2                           ; 25 game frames a second

;; --- Screen -------------------------------------------------------------------
SCR_BITMAP      equ #4000
SCR_ATTR        equ #5800
SCR_LINES       equ 192

BLACK           equ 0
BLUE            equ 1
RED             equ 2
MAGENTA         equ 3
GREEN           equ 4
CYAN            equ 5
YELLOW          equ 6
WHITE           equ 7
PAPER           equ 8               ; PAPER*colour
BRIGHT          equ #40

;; --- Layout (planzx.md 2.1) -----------------------------------------------------
;; The playfield is columns 0-23, the HUD 24-31. A world row is a character
;; row: 8 lines, the same as on the CPC, so heights in lines are the CPC's.
PLAY_W          equ 24              ; bytes
HUD_X           equ 24
HUD_W           equ 8
SIDE_W          equ 6               ; each side
LANE_W          equ 4               ; each of the three lanes
COL_LEFT        equ 0
COL_LANE1       equ SIDE_W          ; 6
COL_RIGHT       equ COL_LANE1+3*LANE_W  ; 18
    assert COL_RIGHT+SIDE_W == PLAY_W
ROW_LINES       equ 8
PICTURE_ROWS    equ 24              ; whole rows on the screen (one more shows in part)
PLAY_LINES      equ PICTURE_ROWS*ROW_LINES
ROW_PIXELS      equ PLAY_W*ROW_LINES    ; 192 bytes of a world row in the ring

;; --- The ring (planzx.md 2.2) -----------------------------------------------------
;; World row n lives in slot (-n) mod RING_SLOTS, its lines top to bottom, so
;; the screen read top to bottom is the ring read upwards in memory. RING_SLOTS
;; rows hold the 25 a picture can show and the one drawn ahead of it, with
;; room to spare. Its size is a whole number of pages, so the end is a page
;; boundary the blit compares H with. After it, a copy of slot 0 (the shadow):
;; a character row read from near the end runs on into it instead of wrapping
;; in the middle.
RING_SLOTS       equ 28
RING_BYTES      equ RING_SLOTS*ROW_PIXELS        ; 5376 = 21 pages
    assert (RING_BYTES & 255) == 0
;; Each world row's attributes, PLAY_W bytes (blit_attrs goes round at the
;; end).
ATTR_RING_BYTES equ RING_SLOTS*PLAY_W

;; --- Memory (planzx.md 2.5) ---------------------------------------------------------
;; The tape loads one block at LOAD_BASE: rarely read data in contended RAM up
;; to #8000, then the code. #5B00-#5FFF is ours once the program runs (it
;; never returns to BASIC): workspace that is not on the tape.
WS_LOW          equ #5B00           ; world ring (64 x 16) and other workspace
WS_LOW_END      equ #6000
LOAD_BASE       equ #6000
CODE_ORG        equ #8000
;; Built at run time, not on the tape: the ring (with its shadow row) and
;; the attribute ring, under the IM 2 table.
RING_ORG        equ #E400
ATTR_RING_ORG   equ RING_ORG+RING_BYTES+ROW_PIXELS
WS_HIGH_END     equ ATTR_RING_ORG+ATTR_RING_BYTES
CODE_LIMIT      equ RING_ORG            ; the loaded block ends below it
ring            equ RING_ORG
attr_ring       equ ATTR_RING_ORG
    assert (RING_ORG & 255) == 0

;; IM 2 as in the Loukoumas port: a 257-byte table of #FC at #FD00 and the
;; jump at #FCFC (a table of #FD would put the jump over #FDFF, where an idle
;; bus reads the vector from). I >= #80, or a 48K shows snow.
IM2_TABLE       equ #FD00
IM2_I           equ IM2_TABLE/256
IM2_FILL        equ IM2_I-1
IM2_JUMP        equ IM2_FILL*257                ; #FCFC
    assert IM2_I >= #80
    assert IM2_JUMP+3 <= IM2_TABLE
    assert WS_HIGH_END <= IM2_JUMP
STACK_TOP       equ #0000           ; first push lands at #FFFF, down to #FE01

;; --- Beam sync (planzx.md 2.2) ----------------------------------------------------
;; How long beam_sync listens to the floating bus before it gives up (a +2A/+3
;; has none): iterations of its 53 T loop, ~16K T - past the start of the
;; picture on a 128K too (T 14362).
SYNC_LIMIT      equ 300
