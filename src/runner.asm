;; ===========================================================================
;; Runner A.P.E.R - Athens Piraeus Electric Railways
;; ZX Spectrum 48K (and 128K) - Z80, rasm. The CPC version's game, the
;; Spectrum's picture, sound and tape (planzx.md).
;;
;; Memory (planzx.md 2.5): one block loaded at LOAD_BASE - data read now and
;; then in contended RAM up to #8000, then the code and the art. The world's
;; ring and the IM 2 table are built at run time above it.
;; ===========================================================================

                include "config.asm"
                include "data/text_ids.asm"

;; --- #6000: data read now and then (contended) ------------------------------
                org LOAD_BASE
data_start:
                include "data/chunks.asm"
                include "data/text.asm"
                include "data/gfx_menu.asm"
data_end:
                assert data_end <= CODE_ORG

;; --- #8000: the code ------------------------------------------------------------
                org CODE_ORG
start:
                di
                ld sp,STACK_TOP
                call screen_clear
                call irq_init
                call kempston_detect
                call sound_init
                xor a                       ; English
                call set_language
                call hud_init
                call new_run
                ld a,(boot_mode)            ; the menu (tests: straight into
                cp MODE_MENU                ; a game)
                call nc,go_menu
                ld a,(boot_mode)
                cp MODE_MENU
                jr nc,main_loop
                ld (game_mode),a

main_loop:
                call wait_game_frame
                push af
                ld a,(game_mode)            ; a still screen: no picture to
                cp MODE_MENU                ; copy, its keys and its tune
                jr c,.playing
                pop af
                call read_input
                call screen_frame
                call sound_frame
                jp main_loop
.playing:       ld a,(paused)               ; paused: the picture stays as
                or a                        ; it is
                jr z,.picture
                pop af
                call read_input
                call play_input
                call sound_frame
                jp main_loop
;; Before the beam reaches the picture (T 14336): if the frame is at its very
;; start, world jobs that fit (world_early). beam_sync waits for the rest. A
;; frame begun late does not know where the beam is: beam_sync_late.
.picture:       pop af
                jr nc,.late
                call world_early
                call beam_sync
                jr .blit
.late:          call beam_sync_late         ; not into a picture being drawn
.blit:          call blit
after_blit:
;; After it, the game frame.
                call read_input
                call play_input             ; 0: on, 1: counting, 2: no more
                cp 1
                jr z,.still
                jp nc,main_loop
                call game_state_update
                jr nz,.not_playing
                call player_update
                call collide
                ld a,(game_state)
                or a
                jr nz,.not_playing
                call pickups
                call magnet
                call tick_powerups
                call stations
.not_playing:   call move_flyers
                call label_frame
                ld a,(game_state)           ; the world stops while crashed
                or a
                ld a,0
                jr nz,.scroll
                call current_speed          ; turbo / slow / normal
.scroll:        call scroll_step
                call c,score_row
.still:         call hud_update
                call sound_frame
                call sprites_clear          ; the sprites, for the next blit
                call player_draw
                call draw_flyers
                call world_jobs
                ld hl,(frame_counter)
                inc hl
                ld (frame_counter),hl
                jp main_loop

;; ---------------------------------------------------------------------------
;; world_jobs - after the game frame's logic. The world is made in jobs, one
;; row at a time: generate it (two halves), then draw it into its slot (the
;; tiles' two halves, each overlay's slice, then ring_done). The ring has
;; slots to spare for three rows above the picture's top, so rows are drawn
;; ahead while there is time; only when the top row is not ready (a burst of
;; coarse steps) must jobs be done there and then.
;;
;; There is time while the game frame's second TV frame lasts: frame_count
;; is one past frame_last until the interrupt at T 139776. After it, the
;; next blit starts at T 14.4K of the new frame; a job may still start if the
;; longest it can take (job_bound), added to the bounds of the one that was
;; running when the interrupt came and of those started since, fits in
;; POST_BUDGET. Rows are generated at most two ahead of the drawn ones (the
;; overlays wait in a list of 16).
;; ---------------------------------------------------------------------------
DRAW_AHEAD      equ 3                       ; rows drawn above the top
    assert PICTURE_ROWS+1+DRAW_AHEAD <= RING_SLOTS
GEN_AHEAD       equ 2                       ; rows generated above the drawn
POST_BUDGET     equ 13600/256               ; T after the interrupt, /256
LOGIC_BOUND     equ 255                     ; (the logic ran into it: no time)

JOB_GEN_SIDES   equ 0
JOB_GEN_TRACK   equ 1
JOB_DRAW        equ 2                       ; + draw_phase

world_jobs:
                ld a,LOGIC_BOUND
                ld (last_bound),a
                ld a,#FF
                ld (post_spent),a
.must:          ld hl,(drawn_row)           ; the top row drawn?
                ld de,(cur_top_row)
                or a
                sbc hl,de
                jr nc,.extra
                call next_job
                ld c,a
                call job_bound
                ld a,b
                ld (last_bound),a
                ld a,c
                call run_job
                jr .must
.extra:         call wanted_job             ; A = job, or C: none wanted
                jr c,.idle
                ld c,a
                call job_bound              ; B = its bound
                ld a,(frame_count)          ; past the interrupt?
                ld hl,frame_last
                sub (hl)
                cp 2
                jr c,.run
                ld a,(post_spent)
                cp #FF
                jr nz,.spent
                ld a,(last_bound)           ; first time: the one running then
.spent:         add a,b
                jr c,.stop
                cp POST_BUDGET+1
                jr nc,.stop
                ld (post_spent),a
.run:           ld a,b
                ld (last_bound),a
                ld a,c
                call run_job
                jr .extra
.stop:          ret
.idle:          ld a,(prewarmed)            ; nothing left: once a frame
                or a
                ret nz
                inc a
                ld (prewarmed),a
                jp chunk_prewarm

;; next_job - A = the next job towards drawing row drawn_row + 1.
next_job:
                ld a,(gen_phase)            ; a row half generated, or
                or a                        ; drawn_row + 1 not generated:
                jr nz,.gen                  ; generate
                ld hl,(drawn_row)
                ld de,(gen_upto)
                or a
                sbc hl,de
                jr nc,.gen
                ld a,(draw_phase)
                add a,JOB_DRAW
                ret
.gen:           ld a,(gen_phase)
                ret

;; wanted_job - A = the job to do next if there is time, or C if the rows
;; are drawn and generated as far ahead as they go.
wanted_job:
                ld a,(draw_phase)           ; a row half drawn: on with it
                or a
                jr nz,next_job
                ld hl,(drawn_row)           ; drawn far enough ahead?
                ld de,(cur_top_row)
                or a
                sbc hl,de
                ld a,l
                cp DRAW_AHEAD
                jr c,next_job
                ld a,(gen_phase)
                or a
                ret nz                      ; (NC)
                ld hl,(gen_upto)            ; generated far enough ahead?
                ld de,(drawn_row)
                or a
                sbc hl,de
                ld a,l
                cp GEN_AHEAD
                ccf
                ld a,JOB_GEN_SIDES
                ret

;; run_job - A = job.
run_job:
                push af
                xor a
                ld (prewarmed),a
                pop af
                cp JOB_GEN_TRACK
                jr c,.sides
                jr z,.track
                ld hl,(drawn_row)           ; a part of drawing drawn_row + 1
                inc hl
                call row_slot
                push hl
                call render_part
                pop hl
                ret nc
                ld (drawn_row),hl
                ret
.sides:         ld a,1
                ld (gen_phase),a
                ld hl,(gen_upto)
                inc hl
                jp gen_sides
.track:         xor a
                ld (gen_phase),a
                ld hl,(gen_upto)
                inc hl
                ld (gen_upto),hl
                jp gen_track

;; job_bound: C = job -> B = the most it can take now, /256 (measured:
;; tools/jobcheck.py). The costly cases are known before: a chunk to pick,
;; a bridge's or a platform's row, slot 0's shadow. Keeps C.
job_bound:
                ld a,c
                cp JOB_GEN_TRACK
                jr c,.table
                jr nz,.draw
                ld b,11600/256              ; the track: a power-up to place
                ld hl,(pu_gap)              ; is dear; so is the chunk picked
                ld a,h                      ; at one's end; in a chunk, a
                or l                        ; spacer or a bridge, cheap
                ret z
                ld a,(chunk_left)
                ld hl,spacer_left
                or (hl)
                ld hl,bridge_left
                or (hl)
                ret z
                ld b,4000/256
                ret
.draw:          push bc                     ; drawing: the row's descriptor
                ld hl,(drawn_row)
                inc hl
                call desc_addr
                pop bc
                ld a,c
                sub JOB_DRAW
                jr nz,.not_top
                bit 7,(hl)                  ; tiles, first half: a bridge does
                ld b,4700/256               ; all of it
                ret z
                ld b,7200/256
                ret
.not_top:       dec a
                jr nz,.not_bottom
                ld a,D_PLAT                 ; second half: a platform's strips
                call add_a_hl
                ld a,(hl)
                or a
                ld b,4000/256
                ret z
                ld b,8700/256
                ret
.not_bottom:    dec a
                ld b,6500/256               ; a slice
                ret z
                push bc                     ; ring_done: slot 0's shadow
                ld hl,(drawn_row)
                inc hl
                call row_slot
                pop bc
                or a
                ld b,1300/256
                ret nz
                ld b,4900/256
                ret
.table:         ld b,8200/256               ; the sides
                ret

;; world_early - at the start of a game frame (T 0, wait_game_frame halted):
;; jobs up to the beam's picture, by their bounds.
world_early:
                ld a,EARLY_BUDGET
                ld (early_left),a
.job:           call wanted_job
                ret c
                ld c,a
                call job_bound
                ld a,(early_left)
                sub b
                ret c
                ld (early_left),a
                ld a,b
                ld (last_bound),a
                ld a,c
                call run_job
                jr .job
EARLY_BUDGET    equ 13000/256               ; T 0 to the picture, less a margin

;; row_slot - HL = world row, no lower than the top: A = its slot (a slot back
;; for every row above the top). Keeps HL. Destroys BC, DE.
row_slot:
                push hl
                ld de,(cur_top_row)
                or a
                sbc hl,de
                ld b,l
                pop hl
                ld a,(top_slot)
                inc b
                jr .test
.up:            call slot_above
.test:          djnz .up
                ret

drawn_row:      defw 0                      ; rows up to it are in the ring
gen_upto:        defw 0                      ; rows up to it are generated
draw_phase:     defb 0                      ; render_part's, for drawn_row + 1
gen_phase:      defb 0                      ; 1: gen_upto + 1 has its sides
prewarmed:      defb 0                      ; chunk_prewarm done, nothing since
last_bound:     defb 0                      ; the bound of the job last started
post_spent:     defb 0                      ; bounds since the interrupt, #FF
early_left:     defb 0                      ; world_early's budget left

;; ---------------------------------------------------------------------------
;; new_run - a fresh world (rows 0 .. PICTURE_ROWS drawn into the ring, the
;; one above them generated), runner and score.
;; ---------------------------------------------------------------------------
new_run:
                call world_init
                call scroll_init
                call player_init
                call pickups_init
                ld a,1
                ld (attr_dirty),a
                ld hl,#FFFF                 ; (deck_flags: all of them again)
                ld (dn_top),hl
                xor a
                ld (draw_phase),a
                ld (gen_phase),a
                ld (game_state),a
                ld (invuln),a
                ld (was_airborne),a
                ld a,LIVES_START
                ld (lives),a
                ld hl,0                     ; rows 0 .. PICTURE_ROWS
                xor a                       ; (A = slot of row HL)
.row:           push hl
                push af
                call draw_world_row
                pop af
                pop hl
                call slot_above
                inc hl
                ld e,a
                ld a,l
                cp PICTURE_ROWS+1
                ld a,e
                jr nz,.row
                dec hl
                ld (drawn_row),hl
                ld (gen_upto),hl
                jp hud_refresh

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

scroll_speed:   defb 4                      ; lines a game frame
skill:          defb 0                      ; 0 easy, 1 medium, 2 hard
gap_hard:       defb 0
frame_counter:  defw 0                      ; game frames
boot_mode:      defb MODE_MENU              ; (tests: MODE_PLAY)

                include "irq.asm"
                include "video.asm"
                include "sprite.asm"
                include "input.asm"
                include "world.asm"
                include "chunk_pick.asm"
                include "player.asm"
                include "collide.asm"
                include "pickups.asm"
                include "text.asm"
                include "hud.asm"
                include "screens.asm"
                include "sound.asm"
                include "data/gfx.asm"
                include "data/gfx_hud.asm"

code_end:
                print "code end ",{hex4}code_end
                assert code_end <= CODE_LIMIT
LOAD_ADDR       equ start
LOAD_CLEAR      equ LOAD_BASE-1
BIN_ORG         equ LOAD_BASE
                save "build/runner.bin",LOAD_BASE,code_end-LOAD_BASE
