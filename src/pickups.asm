; =============================================================================
; Collectibles and power-ups (the CPC's src/pickups.asm, plan.md 1.3 there).
;
; Items live in the row descriptors (D_ITEM) and are drawn into the ring with
; their rows. The runner picks up the item of the cell under its feet (same
; probe as collide) if it is not more than one level above that cell: a coin
; on a roof needs the roof, a high jump flies over coins. A picked-up item
; is erased by drawing its lane's track tile into its rows of the ring again
; (and their attributes): the blit shows it gone in the next picture.
;
; Magnet: coins of the runner's lane and the lanes next to it that reach
; MAGNET_LINE leave the track and fly to the runner as sprites (at most
; FLYER_COUNT at a time), drawn into the ring like the runner.
;
; Score (BCD, 6 digits): 1 point per row run (2 with turbo), 10 per coin
; (20 with the ticket).
; =============================================================================

TURBO_EXTRA     equ 2                   ; turbo: base speed + 2 lines a frame
TURBO_MAX       equ 7                   ; (a coarse step every frame at 8)
COIN_POINTS     equ #10                 ; BCD

MAGNET_LINE     equ FOOT_Y-72           ; screen line where coins take off
FLYER_COUNT     equ 3                   ; (the CPC's 8: the C64's 3)
FLY_SIZE        equ 4
FLY_ACTIVE      equ 0
FLY_X           equ 1                   ; byte column
FLY_Y           equ 2                   ; (2) top screen line
FLY_STEP_Y      equ 24                  ; lines per game frame
FLY_STEP_X      equ 2                   ; bytes per game frame
LABEL_WAGONS    equ 8                   ; show_label: the hard mode hint (txt_pu_wagons),
LABEL_GO        equ 12                  ; then 3, 2, 1 (9-11) and GO!
LABEL_STATION   equ 13                  ; the stations Corinth .. Piraeus (13-18)

; -----------------------------------------------------------------------------
; pickups_init: no score, no power-ups, no flying coins (new run).
; -----------------------------------------------------------------------------
pickups_init:
                ld hl,pickup_state
                ld de,pickup_state+1
                ld bc,PICKUP_STATE_SIZE-1
                ld (hl),0
                ldir
                xor a
                ld (label_wait),a
                ret

; -----------------------------------------------------------------------------
; pickups: after collide, while running. Takes the item under the feet.
; -----------------------------------------------------------------------------
pickups:
                ld a,(no_pickups)           ; test/debug switch
                ld hl,(arc_ptr)             ; in the air: jumps over the items
                or h
                or l
                ret nz
                ld a,(probe_lane)
                ld hl,FEET_PROBE
                call cell_at
                call support_level
                ld b,a
                ld a,(player_z)             ; at most one level above the cell
                sub b
                ret c
                cp 2
                ret nc
                ld hl,(probe_row)
                call desc_addr
                ld a,(probe_lane)
                add D_ITEM
                call add_a_hl
                ld a,(hl)
                or a
                ret z
                ld (hl),0
                push af
                ld c,1                      ; coin: 1 row, power-up: 2
                cp ITEM_COIN
                jr z,.erase
                inc c
.erase:         ld hl,(probe_row)
                ld a,(probe_lane)
                call erase_item
                pop af
                cp ITEM_COIN
                jp z,collect_coin
                ; fall through

; -----------------------------------------------------------------------------
; activate_powerup: A = item 2..7.
; -----------------------------------------------------------------------------
activate_powerup:
                push af
                ld a,SFX_POWERUP
                ld (sfx_request),a
                pop af
                push af
                call make_label             ; its name in the middle of the screen
                pop af
                cp ITEM_HELMET
                jr nz,.timed
                ld (helmet),a               ; non-zero: one crash absorbed
                ret
.timed:         cp ITEM_TURBO               ; turbo and slow cancel each other
                jr nz,.not_turbo
                ld hl,0
                ld (pu_slow),hl
.not_turbo:     cp ITEM_SLOW
                jr nz,.not_slow
                ld hl,0
                ld (pu_turbo),hl
.not_slow:      sub ITEM_MAGNET
                add a,a
                ld e,a
                ld d,0
                ld hl,pu_durations
                add hl,de
                ld c,(hl)
                inc hl
                ld b,(hl)
                ld hl,pu_timers
                add hl,de
                ld (hl),c
                inc hl
                ld (hl),b
                ret

; game frames, by item 2..7 (helmet has no timer)
pu_durations:   defw 250,200,200,250,0,375  ; 10 s, 8 s, 8 s, 10 s, -, 15 s

; -----------------------------------------------------------------------------
; tick_powerups: one game frame off every running timer (paused while the
; runner is crashed).
; -----------------------------------------------------------------------------
tick_powerups:
                ld hl,pu_timers
                ld b,PU_TIMER_COUNT
.next:          ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                or e
                jr z,.idle
                dec de
                ld (hl),d
                dec hl
                ld (hl),e
                inc hl
.idle:          inc hl
                djnz .next
                ret

; A = lines per game frame for the scroll: turbo, slow or the normal speed
current_speed:
                ld hl,(pu_slow)
                ld a,h
                or l
                ld a,(scroll_speed)
                jr z,.not_slow
                srl a                       ; slow: half
                ret
.not_slow:      ld hl,(pu_turbo)
                ld b,a
                ld a,h
                or l
                ld a,b
                ret z
                add TURBO_EXTRA             ; turbo: faster, at most TURBO_MAX
                cp TURBO_MAX+1
                ret c
                ld a,TURBO_MAX
                ret

; -----------------------------------------------------------------------------
; score_row: called for every row the world moves (coarse step).
; -----------------------------------------------------------------------------
score_row:
                ld hl,(distance)
                inc hl
                ld (distance),hl
                ld hl,(pu_turbo)            ; turbo: double distance points
                ld a,h
                or l
                ld a,1
                jr z,score_add
                inc a
                ; fall through

; A = BCD points (0-99) added to the 6-digit BCD score (saturates at 999999)
score_add:
                ld hl,score
                add a,(hl)
                daa
                ld (hl),a
                inc hl
                ld a,(hl)
                adc 0
                daa
                ld (hl),a
                inc hl
                ld a,(hl)
                adc 0
                daa
                ld (hl),a
                ret nc
.full:          ld a,#99                    ; HL = score+2
                ld (hl),a
                dec hl
                ld (hl),a
                dec hl
                ld (hl),a
                ret

; a coin: +1 coin (BCD, saturates at 9999), +10 points (+20 with the ticket)
collect_coin:
                ld a,SFX_COIN
                ld (sfx_request),a
                ld hl,coins
                ld a,(hl)
                add 1
                daa
                ld (hl),a
                inc hl
                ld a,(hl)
                adc 0
                daa
                jr c,.full
                ld (hl),a
.full:          ld hl,(pu_ticket)
                ld a,h
                or l
                ld a,COIN_POINTS
                jr z,score_add
                ld a,COIN_POINTS*2
                jr score_add

; -----------------------------------------------------------------------------
; erase_item: HL = world row, A = lane, C = rows: the lane's track tile drawn
; into those rows of the ring again, and its attributes, if they are still
; in it (the rows of the picture and the one above).
; -----------------------------------------------------------------------------
erase_item:
                ld (.lane),a
                xor a                       ; (rr_* are no longer render_part's)
                ld (rr_mine),a
                ld b,c
.row:           push bc
                push hl
                ex de,hl                    ; picture row = top - world row
                ld hl,(cur_top_row)
                or a
                sbc hl,de
                jr c,.next                  ; above the top: not drawn yet
                ld a,h
                or a
                jr nz,.next
                ld a,l
                cp PICTURE_ROWS+1
                jr nc,.next
                ld b,a                      ; its slot: top_slot + that, round
                ld a,(top_slot)
                add a,b
                cp RING_SLOTS
                jr c,.slot
                sub RING_SLOTS
.slot:          ld (rr_slot),a
                call slot_addr
                ld (rr_dest),hl
                ld a,(rr_slot)
                call attr_slot_addr
                ld (rr_attr),hl
                pop hl
                push hl
                call desc_addr              ; the tile of that lane
                ld a,(.lane)
                add D_LANES
                call add_a_hl
                ld a,(hl)
                ld hl,gfx_track_table
                call table_entry
                ld a,(.lane)
                call lane_column
                ld b,a
                ld c,LANE_W
                call blit_tile
                ld a,(rr_slot)              ; (the attributes' second copy)
                call ring_done
                ld a,1                      ; the blit: write them again
                ld (attr_dirty),a
.next:          pop hl
                inc hl
                pop bc
                djnz .row
                ret
.lane:          defb 0

; -----------------------------------------------------------------------------
; magnet: while it runs, the coins near the runner's lane that reach
; MAGNET_LINE take off as flying sprites.
; -----------------------------------------------------------------------------
magnet:
                ld a,(no_pickups)
                or a
                ret nz
                ld hl,(pu_magnet)
                ld a,h
                or l
                ret z
                ld hl,MAGNET_LINE           ; world row at the magnet line
                ld a,(cur_j)
                add a,l
                ld l,a
                jr nc,.nc
                inc h
.nc:            srl h
                rr l
                srl l
                srl l
                ld a,l
                ld (.picture_row),a
                ex de,hl
                ld hl,(cur_top_row)
                or a
                sbc hl,de
                ld (.world_row),hl
                xor a
.lane:          ld (.lane_no),a
                ld b,a                      ; |lane - player_lane| <= 1
                ld a,(player_lane)
                sub b
                jr nc,.dist
                neg
.dist:          cp 2
                jr nc,.next_lane
                ld hl,(.world_row)
                call desc_addr
                ld a,(.lane_no)
                add D_ITEM
                call add_a_hl
                ld a,(hl)
                cp ITEM_COIN
                jr nz,.next_lane
                call free_flyer             ; IX = free slot, or NZ if none
                jr nz,.next_lane
                ld (hl),0
                ld (ix+FLY_ACTIVE),1
                ld a,(.lane_no)             ; coin column (as spawn_item)
                call lane_column
                add ITEM_X
                ld (ix+FLY_X),a
                ld a,(.picture_row)         ; top line = row*8 - j
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld a,(cur_j)
                ld e,a
                ld d,0
                or a
                sbc hl,de
                ld (ix+FLY_Y),l
                ld (ix+FLY_Y+1),h
                ld hl,(.world_row)
                ld a,(.lane_no)
                ld c,1
                call erase_item
.next_lane:     ld a,(.lane_no)
                inc a
                cp 3
                jr nz,.lane
                ret
.picture_row:   defb 0
.world_row:     defw 0
.lane_no:       defb 0

; IX = a free flyer slot (Z), or NZ if all are flying. Destroys A, B, DE.
free_flyer:
                ld ix,flyers
                ld de,FLY_SIZE
                ld b,FLYER_COUNT
.slot:          ld a,(ix+FLY_ACTIVE)
                or a
                ret z
                add ix,de
                djnz .slot
                or 1
                ret

; -----------------------------------------------------------------------------
; move_flyers: every flying coin heads for the runner's chest; it is
; collected when it gets there.
; -----------------------------------------------------------------------------
move_flyers:
                ld a,(player_z)             ; target line = FOOT_Y-2z-14
                add a,a
                neg
                add (FOOT_Y-14) & #FF
                ld (.target_y),a            ; (high byte is 0 for every z)
                ld a,(player_centre)
                sub ITEM_W/2
                ld (.target_x),a
                ld ix,flyers
                ld b,FLYER_COUNT
.slot:          push bc
                ld a,(ix+FLY_ACTIVE)
                or a
                jr z,.next
                ld c,0                      ; C = axes still on their way
                ld a,(.target_x)            ; x: FLY_STEP_X towards the target
                sub (ix+FLY_X)
                jr z,.x_done
                inc c
                jr c,.left
                cp FLY_STEP_X
                jr c,.x_add
                ld a,FLY_STEP_X
.x_add:         add a,(ix+FLY_X)
                ld (ix+FLY_X),a
                jr .x_done
.left:          neg
                cp FLY_STEP_X
                jr c,.x_sub
                ld a,FLY_STEP_X
.x_sub:         ld b,a
                ld a,(ix+FLY_X)
                sub b
                ld (ix+FLY_X),a
.x_done:        ld l,(ix+FLY_Y)             ; y: down, FLY_STEP_Y at a time
                ld h,(ix+FLY_Y+1)
                ld a,(.target_y)
                ld e,a
                ld d,0
                ex de,hl
                or a
                sbc hl,de                   ; HL = target - y
                jr c,.y_done                ; already below: stay
                jr z,.y_done
                inc c
                ld a,h
                or a
                jr nz,.y_step
                ld a,l
                cp FLY_STEP_Y
                jr c,.y_add
.y_step:        ld hl,FLY_STEP_Y
.y_add:         add hl,de
                ld (ix+FLY_Y),l
                ld (ix+FLY_Y+1),h
.y_done:        ld a,c
                or a
                jr nz,.next
                ld (ix+FLY_ACTIVE),0        ; arrived
                call collect_coin
.next:          ld de,FLY_SIZE
                add ix,de
                pop bc
                djnz .slot
                ret
.target_y:      defb 0
.target_x:      defb 0

; -----------------------------------------------------------------------------
; draw_flyers: the flying coins, for the blit to draw (src/sprite.asm).
; -----------------------------------------------------------------------------
draw_flyers:
                ld a,(anim_tick)            ; spinning coin: coin0..coin3
                rra
                and 3
                ld hl,gfx_items_table
                call table_entry
                ld (.sprite),hl
                ld hl,flyers
                ld b,FLYER_COUNT
.slot:          push bc
                push hl
                ld a,(hl)                   ; FLY_ACTIVE
                or a
                jr z,.next
                inc hl
                ld c,(hl)                   ; FLY_X
                inc hl
                ld a,(hl)                   ; FLY_Y (below 192)
                ld l,a
                ld ix,(.sprite)
                ld b,0
                call sprite_add
.next:          pop hl
                ld de,FLY_SIZE
                add hl,de
                pop bc
                djnz .slot
                ret
.sprite:        defw 0

; --- state (cleared by pickups_init) -------------------------------------------
pickup_state:
score:          defs 3                  ; BCD, low byte first
coins:          defs 2                  ; BCD, low byte first
distance:       defw 0                  ; rows run
helmet:         defb 0                  ; non-zero: the next crash is absorbed
pu_timers:                              ; game frames left, by item 2..7
pu_magnet:      defw 0
pu_turbo:       defw 0
pu_slow:        defw 0
pu_spring:      defw 0
pu_helmet:      defw 0                  ; (unused: the helmet has no timer)
pu_ticket:      defw 0
PU_TIMER_COUNT       equ ($-pu_timers)/2
flyers:         defs FLYER_COUNT*FLY_SIZE
PICKUP_STATE_SIZE equ $-pickup_state
no_pickups:     defb 0                  ; debug: items are never picked up
