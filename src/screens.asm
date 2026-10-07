; =============================================================================
; Screens and game flow: menu, controls, story, high scores, game over with
; name entry, attract-mode demo, pause, the start's countdown (the CPC's
; src/screens.asm).
;
; A still screen is drawn once on the playfield while the world stands
; still: the blit is not run, so nothing else touches those columns. The HUD
; stays next to it. A game or a demo starts with new_run, which draws the
; whole world into the ring again, and the next blit brings it back.
;
; Texts come in two languages (English by default, L switches to Greek on
; the menu, controls, story and high score screens): set_language copies the
; language's pointer table to text_ptrs, and "ld hl,(txt_<name>)" reads it.
; =============================================================================

MODE_PLAY       equ 0
MODE_DEMO       equ 1
MODE_MENU       equ 2                   ; modes >= MODE_MENU: a still screen
MODE_CONTROLS   equ 3
MODE_SCORES     equ 4
MODE_OVER       equ 5
MODE_STORY      equ 6

MENU_ITEMS      equ 7
MENU_ROW        equ 9                   ; first option's character row
MENU_COL        equ 4                   ; the options' column
ATTRACT_FRAMES  equ 400                 ; 16 s on the menu: the demo starts
DEMO_FRAMES     equ 750                 ; 30 s of demo
HISCORES        equ 8
HS_SIZE         equ 6                   ; score (3, BCD), name (3 letters 0-25)
NAME_LETTERS    equ 3
SKILL_HARD      equ 2
TITLE_ATTR      equ BRIGHT+YELLOW
TEXT_ATTR       equ BRIGHT+WHITE
HINT_ATTR       equ CYAN
LOGO_COL        equ (PLAY_W-GFX_LOGO_W)/2
LOGO_ROW        equ 1

; -----------------------------------------------------------------------------
; Mode changes
; -----------------------------------------------------------------------------
go_menu:
                ld a,MODE_MENU
set_screen:     ld (game_mode),a
                ld a,1
                ld (screen_dirty),a
                xor a
                ld (menu_idle),a
                ld (menu_idle+1),a
                ld (paused),a
                ld hl,0                     ; (the HUD's label: none)
                jp hud_label

start_game:                                 ; at the chosen difficulty
                call new_run
                ld a,(skill)
                ld hl,skill_speeds
                call add_a_hl
                ld a,(hl)
                ld (scroll_speed),a
                ld a,(skill)                ; hard: jump between the wagons
                cp SKILL_HARD
                ld a,0
                jr nz,.gaps
                inc a
.gaps:          ld (gap_hard),a
                add a,a                     ; countdown: 3, 2, 1, GO! (and on
                add a,a                     ; hard the wagons hint before it)
                add a,a
                add a,a
                add a,a
                add a,a                     ; (hard: 64 more frames)
                add a,COUNT_STEP*3+(COUNT_STEP>>1)
                ld (countdown),a
                ld a,1
                ld (count_first),a
                xor a                       ; MODE_PLAY
                ld (game_mode),a
                ret
skill_speeds:   defb 4,5,6                  ; lines a game frame: easy, medium, hard

start_demo:
                call new_run
                ld a,MODE_DEMO
                ld (game_mode),a
                ld hl,DEMO_FRAMES
                ld (demo_timer),hl
                ld hl,(txt_demo)
                jp hud_label

; game_state_update: the game-over wait ended
game_finished:
                ld a,(game_mode)
                cp MODE_DEMO
                jr z,go_menu
                ld a,MODE_OVER
                call set_screen
                xor a
                ld (name_pos),a
                ld (name_buf),a
                ld (name_buf+1),a
                ld (name_buf+2),a
                call score_rank             ; A = place in the table, HISCORES = none
                ld (over_rank),a
                ret

; -----------------------------------------------------------------------------
; play_input: the playing modes, after read_input. A = 0: the game goes on;
; 1: the world stands (the countdown), but the runner is drawn; 2: nothing
; more this frame (paused, or back to the menu).
; -----------------------------------------------------------------------------
play_input:
                ld a,(game_mode)
                cp MODE_DEMO
                jr nz,.player
                ld a,(keys_pressed)         ; demo: any key back to the menu
                or a
                jr nz,.to_menu
                ld hl,(demo_timer)
                dec hl
                ld (demo_timer),hl
                ld a,h
                or l
                jr z,.to_menu
                call demo_ai                ; the demo's own keys
                xor a
                ret
.to_menu:       call go_menu
                ld a,2
                ret
.player:        ld a,(countdown)
                or a
                jr nz,countdown_frame
                ld a,(keys_pressed)
                and KEY_ESC
                jr nz,.to_menu
                ld bc,ROW_SPACE*256+KEY_M_MASK  ; M: music on/off
                ld hl,music_key_down
                call matrix_edge
                jr z,.music_ok
                ld hl,music_on
                ld a,(hl)
                xor 1
                ld (hl),a
.music_ok:      ld a,(keys_pressed)         ; H toggles the pause
                and KEY_PAUSE
                jr z,.pause_ok
                ld a,(paused)
                xor 1
                ld (paused),a
                call pause_label
.pause_ok:      ld a,(paused)
                or a
                ret z
                ld a,2
                ret
KEY_M_MASK      equ %00100              ; M on its half-row (SPACE SYM M N B)
KEY_L_MASK      equ %00010              ; L on its half-row (ENTER L K J H)

; the start of a game: the runner stands still, the hint (hard), then
; 3, 2, 1 and GO! written on the track. A = 1 while counting.
COUNT_STEP      equ 20                  ; game frames per number

countdown_frame:
                dec a
                ld (countdown),a
                jr nz,.counting
                ld a,LABEL_GO               ; GO!: the game runs
                ld c,COUNT_ROW
                call show_label
                xor a
                ret
.counting:      ld b,a
                ld hl,count_first           ; first frame: on hard the hint
                ld a,(hl)
                or a
                jr z,.numbers
                ld (hl),0
                ld a,(gap_hard)
                or a
                jr z,.numbers
                push bc
                ld a,LABEL_WAGONS
                ld c,LABEL_ROW
                call show_label
                pop bc
.numbers:       ld a,b                      ; 60, 40, 20 frames left: 3, 2, 1
                ld c,LABEL_GO-3
                cp COUNT_STEP*3
                jr z,.show
                inc c
                cp COUNT_STEP*2
                jr z,.show
                inc c
                cp COUNT_STEP
                jr nz,.wait
.show:          ld a,c
                ld c,COUNT_ROW
                call show_label
.wait:          ld a,1
                ret

; PAUSE in the HUD panel (the picture is still while paused)
pause_label:
                ld hl,0
                ld a,(paused)
                or a
                jp z,hud_label
                ld hl,(txt_pause)
                jp hud_label

; -----------------------------------------------------------------------------
; set_language: A = language (0 English, 1 Greek) -> text_ptrs.
; -----------------------------------------------------------------------------
set_language:
                ld (language),a
                add a,a
                ld hl,text_ptr_tables
                call add_a_hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld de,text_ptrs
                ld bc,TXT_COUNT*2
                ldir
                ret

; L on the menu, controls, story and high score screens: the other language,
; the screen drawn again.
language_key:
                ld bc,ROW_ENTER*256+KEY_L_MASK
                ld hl,lang_key_down
                call matrix_edge
                ret z
                ld a,(language)
                inc a
                cp LANGUAGES
                jr c,.set
                xor a
.set:           call set_language
                ld a,1
                ld (screen_dirty),a
                ret

; B = keyboard half-row, C = key mask, HL = its "down" flag: NZ if the key
; went down since the last call
matrix_edge:
                push hl
                ld hl,matrix
                ld a,b
                call add_a_hl
                ld a,(hl)
                and c
                pop hl
                ld b,(hl)
                ld (hl),a
                ret z                       ; up
                ld a,b
                cp 1                        ; was up (0): C, else NC
                sbc a,a                     ; -> #FF / 0
                or a
                ret

; -----------------------------------------------------------------------------
; screen_frame: one game frame of a still screen.
; -----------------------------------------------------------------------------
screen_frame:
                ld a,(game_mode)
                cp MODE_OVER
                call nz,language_key
                ld a,(screen_dirty)
                or a
                call nz,draw_screen
                ld a,(game_mode)
                cp MODE_MENU
                jr z,menu_frame
                cp MODE_OVER
                jp z,over_frame
                ld a,(keys_pressed)         ; controls / scores / story: back
                and KEY_FIRE|KEY_ESC
                ret z
                jp go_menu

menu_frame:
                ld hl,(menu_idle)           ; attract mode after a while
                inc hl
                ld (menu_idle),hl
                ld de,ATTRACT_FRAMES
                or a
                sbc hl,de
                jp z,start_demo
                ld a,(keys_pressed)
                or a
                ret z
                ld hl,0
                ld (menu_idle),hl
                ld b,a
                and KEY_UP
                jr z,.not_up
                ld a,(menu_sel)
                or a
                ret z
                dec a
                jr .move
.not_up:        ld a,b
                and KEY_DOWN
                jr z,.not_down
                ld a,(menu_sel)
                cp MENU_ITEMS-1
                ret z
                inc a
.move:          push af
                call menu_cursor_erase
                pop af
                ld (menu_sel),a
                jp menu_cursor_draw
.not_down:      ld a,b
                and KEY_FIRE
                ret z
                ld a,(menu_sel)
                or a
                jp z,start_game
                cp 4
                jr nc,.option
                ld hl,menu_modes-1          ; 1-3: controls, scores, story
                call add_a_hl
                ld a,(hl)
                jp set_screen
.option:        ld hl,skill                 ; 4: difficulty easy/medium/hard
                jr nz,.flag
                ld a,(hl)
                inc a
                cp 3
                jr c,.set
                xor a
                jr .set
.flag:          ld hl,music_on              ; 5: music, 6: all sound
                cp 5
                jr z,.toggle
                ld hl,sound_on
.toggle:        ld a,(hl)
                xor 1
.set:           ld (hl),a
                ld a,1                      ; the menu drawn again
                ld (screen_dirty),a
                ret
menu_modes:     defb MODE_CONTROLS,MODE_SCORES,MODE_STORY

over_frame:
                ld a,(over_rank)
                cp HISCORES
                jr nc,.done                 ; no record: wait for fire
                ld a,(name_pos)
                cp NAME_LETTERS
                jr nc,.done
                ld a,(keys_pressed)         ; up/down: letter, fire: next
                ld b,a
                ld hl,name_buf
                ld a,(name_pos)
                call add_a_hl
                ld a,b
                and KEY_UP
                jr z,.not_up
                ld a,(hl)
                inc a
                cp 26
                jr c,.set
                xor a
                jr .set
.not_up:        ld a,b
                and KEY_DOWN
                jr z,.not_down
                ld a,(hl)
                dec a
                jp p,.set
                ld a,25
.set:           ld (hl),a
                jp draw_name
.not_down:      ld a,b
                and KEY_FIRE
                ret z
                ld hl,name_pos
                inc (hl)
                ld a,(hl)
                cp NAME_LETTERS
                jp nz,draw_name
                call insert_score           ; name done (kept while the
                call draw_name              ; Spectrum is on)
                ld a,TEXT_ATTR
                ld (print_attr),a
                ld hl,(txt_over_continue)
                ld c,OVER_CONT_ROW
                jp draw_text_centred
.done:          ld a,(keys_pressed)
                and KEY_FIRE|KEY_ESC
                ret z
                ld a,MODE_SCORES
                jp set_screen

; -----------------------------------------------------------------------------
; draw_screen: the whole still screen of the current mode.
; -----------------------------------------------------------------------------
draw_screen:
                xor a
                ld (screen_dirty),a
                call playfield_clear
                ld a,TEXT_ATTR
                ld (print_attr),a
                ld a,(game_mode)
                cp MODE_CONTROLS
                jp z,draw_controls
                cp MODE_SCORES
                jp z,draw_scores
                cp MODE_OVER
                jp z,draw_over
                cp MODE_STORY
                jp z,draw_story
                call draw_logo              ; the menu
                ld hl,menu_lines            ; the options
                ld c,MENU_ROW
.option:        push bc
                ld e,(hl)                   ; DE = first text pointer
                inc hl
                ld d,(hl)
                inc hl
                ld a,(hl)                   ; its variable (0: none)
                inc hl
                ld b,(hl)
                inc hl
                push hl
                ld l,a
                ld h,b
                or h
                jr z,.text                  ; text pointer += 2 * variable
                ld a,(hl)                   ; (on/off: off first)
                add a,a
.text:          ex de,hl
                call add_a_hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                pop de
                pop bc
                push de
                push bc
                ld b,MENU_COL
                call draw_text
                pop bc
                pop hl
                inc c
                ld a,c
                cp MENU_ROW+MENU_ITEMS
                jr nz,.option
                ld a,HINT_ATTR
                ld (print_attr),a
                ld hl,(txt_menu_hint)
                ld c,17
                call draw_text_centred
                ld hl,(txt_menu_lang)
                ld c,18
                call draw_text_centred
                ld a,TITLE_ATTR
                ld (print_attr),a
                ld hl,(txt_menu_credit)
                ld c,20
                call draw_text_centred
                ld hl,(txt_menu_credit2)
                ld c,21
                call draw_text_centred
                ld a,TEXT_ATTR
                ld (print_attr),a
                ld hl,(txt_menu_credit3)
                ld c,23
                call draw_text_centred
                jp menu_cursor_draw

; option texts: first text pointer, variable choosing the text (0: none)
menu_lines:     defw txt_menu_start,0, txt_menu_controls,0, txt_menu_scores,0
                defw txt_menu_story,0, txt_menu_skill_0,skill
                defw txt_menu_music_off,music_on, txt_menu_sound_off,sound_on

menu_cursor_draw:
                ld hl,cursor_text
                jr menu_cursor
menu_cursor_erase:
                ld hl,blank_text
menu_cursor:    ld a,TITLE_ATTR
                ld (print_attr),a
                ld a,(menu_sel)
                add a,MENU_ROW
                ld c,a
                ld b,MENU_COL-2
                jp draw_text
cursor_text:    defb GLYPH_RIGHT,TXT_END
blank_text:     defb GLYPH_SPACE,TXT_END

; the logo: GFX_LOGO_W cells by GFX_LOGO_H rows, their lines from the top,
; then their attributes
draw_logo:
                ld hl,gfx_logo
                ld c,LOGO_ROW
.row:           ld b,LOGO_COL               ; a cell row: its 8 lines
                push hl
                call cell_addr
                ex de,hl                    ; DE = the screen
                pop hl
                ld b,8
.line:          push bc
                push de
                ld bc,GFX_LOGO_W
                ldir
                pop de
                inc d
                pop bc
                djnz .line
                inc c
                ld a,c
                cp LOGO_ROW+GFX_LOGO_H
                jr nz,.row
                ld c,LOGO_ROW               ; the attributes
.attr:          ld b,LOGO_COL
                push hl
                call cell_addr
                call cell_attr
                ex de,hl
                pop hl
                push bc
                ld bc,GFX_LOGO_W
                ldir
                pop bc
                inc c
                ld a,c
                cp LOGO_ROW+GFX_LOGO_H
                jr nz,.attr
                ret

draw_controls:
                call draw_title_controls
                ld hl,controls_lines
                ld c,4
.line:          ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld a,d
                or e
                jr z,.back
                push hl
                push bc
                ex de,hl                    ; HL = the text's pointer
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld b,2
                call draw_text
                pop bc
                pop hl
                inc c
                inc c
                jr .line
.back:          ld c,21
                jp draw_back
draw_title_controls:
                ld hl,(txt_controls_title)
; HL = title text: in yellow on row 1
draw_title:
                ld a,TITLE_ATTR
                ld (print_attr),a
                ld c,1
                call draw_text_centred
                ld a,TEXT_ATTR
                ld (print_attr),a
                ret
; "SPACE : BACK" on row C
draw_back:
                ld a,HINT_ATTR
                ld (print_attr),a
                ld hl,(txt_controls_back)
                jp draw_text_centred
; pointers to the text pointers (text_ptrs)
controls_lines: defw txt_controls_left,txt_controls_right,txt_controls_jump,txt_controls_down
                defw txt_controls_pause,txt_controls_esc,txt_controls_music,txt_controls_joy,0

; the story: title, then centred lines
STORY_ROW       equ 4

draw_story:
                ld hl,(txt_story_title)
                call draw_title
                ld hl,story_lines
                ld c,STORY_ROW
.line:          ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld a,d
                or e
                jr z,.back
                push hl
                push bc
                ex de,hl                    ; HL = the text's pointer
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                call draw_text_centred
                pop bc
                pop hl
                inc c
                jr .line
.back:          ld c,21
                jp draw_back
; pointers to the text pointers (text_ptrs)
story_lines:    defw txt_story_1,txt_story_2,txt_story_3,txt_story_4,txt_story_5
                defw txt_story_6,txt_story_7,txt_story_8,txt_story_9,txt_story_10
                defw txt_story_11,txt_story_12,txt_story_13,txt_story_14,txt_story_15,0

draw_scores:
                ld hl,(txt_scores_title)
                call draw_title
                ld ix,hiscore_table
                ld b,0                      ; B = place
.entry:         push bc
                ld hl,text_buf              ; "N. ABC 012345"
                ld a,b
                inc a
                add a,GLYPH_N0
                ld (hl),a
                inc hl
                ld (hl),GLYPH_DOT
                inc hl
                ld (hl),GLYPH_SPACE
                inc hl
                ld b,NAME_LETTERS
                push ix
.letter:        ld a,(ix+3)
                add a,GLYPH_A
                ld (hl),a
                inc hl
                inc ix
                djnz .letter
                pop ix
                ld (hl),GLYPH_SPACE
                inc hl
                push ix
                pop de
                inc de
                inc de                      ; most significant byte
                ld b,3
                call bcd_text
                ld (hl),TXT_END
                pop bc
                push bc
                ld a,b                      ; row 4 + 2 * place
                add a,a
                add a,4
                ld c,a
                ld hl,text_buf
                call draw_text_centred
                ld de,HS_SIZE
                add ix,de
                pop bc
                inc b
                ld a,b
                cp HISCORES
                jr nz,.entry
                ld c,21
                jp draw_back

OVER_CONT_ROW   equ 21

draw_over:
                ld hl,(txt_over_title)
                call draw_title
                ld hl,(txt_over_score)        ; score
                ld bc,2*256+5
                call draw_text
                ld hl,text_buf
                ld de,score+2
                ld b,3
                call bcd_text
                ld (hl),TXT_END
                ld hl,text_buf
                ld bc,16*256+5
                call draw_text
                ld hl,(txt_over_coins)        ; coins
                ld bc,2*256+7
                call draw_text
                ld hl,text_buf
                ld de,coins+1
                ld b,2
                call bcd_text
                ld (hl),TXT_END
                ld hl,text_buf
                ld bc,18*256+7
                call draw_text
                ld hl,(txt_over_dist)         ; distance (rows)
                ld bc,2*256+9
                call draw_text
                ld hl,(distance)
                call dec_text
                ld hl,text_buf
                ld bc,17*256+9
                call draw_text
                ld a,(over_rank)
                cp HISCORES
                jr nc,.no_record
                ld a,TITLE_ATTR
                ld (print_attr),a
                ld hl,(txt_over_record)
                ld c,12
                call draw_text_centred
                ld a,TEXT_ATTR
                ld (print_attr),a
                ld hl,(txt_over_name)
                ld bc,7*256+14
                call draw_text
                ld a,HINT_ATTR
                ld (print_attr),a
                ld hl,(txt_over_name_hint)
                ld c,18
                call draw_text_centred
                jp draw_name
.no_record:     ld a,HINT_ATTR
                ld (print_attr),a
                ld hl,(txt_over_continue)
                ld c,OVER_CONT_ROW
                jp draw_text_centred

; the name being typed, with a marker under the letter being set
NAME_COL        equ 13
draw_name:
                ld a,TITLE_ATTR
                ld (print_attr),a
                ld hl,text_buf
                ld de,name_buf
                ld b,NAME_LETTERS
.letter:        ld a,(de)
                add a,GLYPH_A
                ld (hl),a
                inc hl
                inc de
                djnz .letter
                ld (hl),TXT_END
                ld hl,text_buf
                ld bc,NAME_COL*256+14
                call draw_text
                ld hl,text_buf              ; markers
                ld a,(name_pos)
                ld c,a
                ld b,0
.mark:          ld a,b
                cp c
                ld a,GLYPH_UP
                jr z,.store
                ld a,GLYPH_SPACE
.store:         ld (hl),a
                inc hl
                inc b
                ld a,b
                cp NAME_LETTERS
                jr nz,.mark
                ld (hl),TXT_END
                ld hl,text_buf
                ld bc,NAME_COL*256+15
                jp draw_text

; the playfield's columns blank, white on black
playfield_clear:
                ld c,0
.row:           ld b,0
                ld de,PLAY_W*256+TEXT_ATTR
                call clear_cells
                inc c
                ld a,c
                cp 24
                jr nz,.row
                ret

; -----------------------------------------------------------------------------
; High scores (in memory while the Spectrum is on: a tape is not a disc)
; -----------------------------------------------------------------------------
; A = place (0-7) the current score would take, HISCORES if none
score_rank:
                ld ix,hiscore_table
                ld b,0
.entry:         ld a,(score+2)              ; compare from the top byte
                cp (ix+2)
                jr c,.lower
                jr nz,.higher
                ld a,(score+1)
                cp (ix+1)
                jr c,.lower
                jr nz,.higher
                ld a,(score)
                cp (ix+0)
                jr c,.lower
                jr z,.lower                 ; equal: below the older one
.higher:        ld a,b
                ret
.lower:         ld de,HS_SIZE
                add ix,de
                inc b
                ld a,b
                cp HISCORES
                jr nz,.entry
                ret

; puts score + name_buf at over_rank, moving the ones below down
insert_score:
                ld a,(over_rank)
                cp HISCORES
                ret nc
                ld b,a                      ; entries to move: 7 - rank
                ld a,HISCORES-1
                sub b
                jr z,.place
                ld c,a                      ; move bytes from the end backwards
                xor a
                ld b,HS_SIZE
.mul:           add a,c
                djnz .mul
                ld c,a
                ld b,0
                ld hl,hiscore_table+(HISCORES-1)*HS_SIZE-1
                ld de,hiscore_table+HISCORES*HS_SIZE-1
                lddr
.place:         ld a,(over_rank)
                ld b,a
                ld hl,hiscore_table
                ld de,HS_SIZE
                inc b
                jr .find_test
.find:          add hl,de
.find_test:     djnz .find
                ex de,hl
                ld hl,score
                ld bc,3
                ldir
                ld hl,name_buf
                ld bc,NAME_LETTERS
                ldir
                ret

; -----------------------------------------------------------------------------
; demo_ai: keys for the attract mode. Looks a few rows ahead in the runner's
; lane; moves to a free neighbouring lane, or jumps a buffer stop.
; -----------------------------------------------------------------------------
DEMO_LOOK       equ 4                   ; rows ahead

demo_ai:
                xor a
                ld (keys_pressed),a
                ld (keys_held),a
                ld a,(move_steps_left)      ; busy moving or jumping
                ld hl,(arc_ptr)
                or h
                or l
                ret nz
                ld a,(player_base)          ; on a roof: stay on it
                or a
                ret nz
                ld a,(player_lane)
                call lane_danger            ; A = 0 free, 1 a stop, 2 blocked
                or a
                ret z
                cp 1                        ; a stop right in front: jump it
                jr nz,.move
                ld a,(demo_near)
                or a
                jr z,.move
                ld a,KEY_JUMP
                jr .keys
.move:          ld a,(player_lane)          ; a free lane next to us?
                or a
                jr z,.try_right
                dec a
                call lane_danger
                or a
                ld a,KEY_LEFT
                jr z,.keys
.try_right:     ld a,(player_lane)
                cp 2
                ret z
                inc a
                call lane_danger
                or a
                ret nz
                ld a,KEY_RIGHT
.keys:          ld (keys_pressed),a
                ld (keys_held),a
                ret

; A = lane: 0 if the next DEMO_LOOK rows are clear from the ground, 1 if the
; first obstacle is a buffer stop (demo_near: it is the next row), 2 if
; something blocks (a train, a red signal, a stop further on).
lane_danger:
                ld (.lane),a
                xor a
                ld (demo_near),a
                ld hl,FRONT_PROBE
                ld b,DEMO_LOOK
.row:           push bc
                push hl
                ld a,(.lane)
                call cell_at
                pop hl
                pop bc
                cp COL_STOP
                jr z,.stop
                cp COL_TRAIN
                jr z,.blocked
                cp COL_NOSE
                jr z,.blocked
                cp COL_GAP
                jr z,.blocked
                cp COL_SIGNAL
                jr nz,.next
                ld a,(signal_red)
                or a
                jr nz,.blocked
.next:          ld de,-8
                add hl,de
                djnz .row
                xor a
                ret
.stop:          ld a,b                      ; the first row looked at?
                cp DEMO_LOOK
                jr nz,.blocked_or_far
                ld a,1
                ld (demo_near),a
                ret
.blocked_or_far:
                ld a,1
                ret
.blocked:       ld a,2
                ret
.lane:          defb 0

; --- state ---------------------------------------------------------------------------
game_mode:      defb MODE_MENU
screen_dirty:   defb 1
menu_sel:       defb 0
menu_idle:      defw 0
demo_timer:     defw 0
demo_near:      defb 0
sound_on:       defb 1                  ; all sound
music_on:       defb 1                  ; the tunes (M while playing)
music_key_down: defb 0
countdown:      defb 0                  ; game frames of the start countdown
count_first:    defb 0
paused:         defb 0
language:       defb 0                  ; 0 English, 1 Greek (set_language)
lang_key_down:  defb 0
over_rank:      defb 0
name_pos:       defb 0
name_buf:       defs NAME_LETTERS
text_ptrs:      defs TXT_COUNT*2        ; the language's (set_language)

; table: score (BCD, low byte first), name (letters 0-25)
macro HS_ENTRY hi,mid,lo,a,b,c
                defb {lo},{mid},{hi},{a},{b},{c}
mend
hiscore_table:
                HS_ENTRY #02,#00,#00,0,15,4         ; APE  20000
                HS_ENTRY #01,#50,#00,17,20,13       ; RUN  15000
                HS_ENTRY #01,#20,#00,15,8,17        ; PIR  12000
                HS_ENTRY #01,#00,#00,0,19,7         ; ATH  10000
                HS_ENTRY #00,#75,#00,10,8,5         ; KIF   7500
                HS_ENTRY #00,#50,#00,13,4,14        ; NEO   5000
                HS_ENTRY #00,#25,#00,12,0,17        ; MAR   2500
                HS_ENTRY #00,#10,#00,5,0,11         ; FAL   1000
