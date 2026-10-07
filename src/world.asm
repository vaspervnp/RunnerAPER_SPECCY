; =============================================================================
; World: generates one map row at a time (world row n, growing upwards) and
; draws it into its slot of the ring (src/video.asm).
;
;   generate_row  - fills the row descriptor in world_ring (n & 63):
;                   environment (urban/forest + 2-row transitions), side tiles,
;                   bridges, track lanes from chunks (levels/chunks), scenery
;                   and item overlays.
;   render_row    - its tiles and the part of every active overlay that falls
;                   in it, pixels and attributes.
;
; The CPC's generator (src/world.asm and src/chunk_pick.asm there), decision
; for decision and random number for random number, without what the
; Spectrum leaves out (planzx.md 1): the moving trains and cars, the day and
; the night. Overlays (cars, trees, coins, power-ups) are registered when
; their BOTTOM row is generated; rows are generated bottom-up, so each later
; row draws its slice and the overlay is freed after its top row.
; =============================================================================

; --- row descriptor -------------------------------------------------------------
ROW_SIZE        equ 16
RING_ROWS       equ 64                  ; power of two
D_FLAGS         equ 0                   ; bit0 forest tile set, bit6 overlay drawn, bit7 bridge
D_LEFT          equ 1                   ; side tile index (or bridge tile index)
D_RIGHT         equ 2                   ; side tile index (mirrored entries)
D_LANES         equ 3                   ; 3 track tile indices
D_COLL          equ 6                   ; 3 collision classes (see tools/mklevel.py)
D_ITEM          equ 9                   ; 3 items
D_PLAT          equ 12                  ; a station's platform: rows left
F_FOREST        equ 1
F_STATION       equ 2                   ; a station on the route (its name)
F_PLATFORM      equ #10
F_LABEL         equ #20                 ; a name written over it (src/text.asm)
F_OVERLAY       equ #40
F_BRIDGE        equ #80

; collision classes (low nibble), high nibble = ramp row
COL_NONE        equ 0
COL_STOP        equ 1
COL_SIGNAL      equ 2
COL_TRAIN       equ 3
COL_NOSE        equ 4
COL_RAMP_UP     equ 5
COL_RAMP_DOWN   equ 6
COL_GAP         equ 7                   ; between two wagons (hard: a gap on the roof)

ITEM_COIN       equ 1
ITEM_MAGNET     equ 2
ITEM_TURBO      equ 3
ITEM_SLOW       equ 4
ITEM_SPRING     equ 5
ITEM_HELMET     equ 6
ITEM_TICKET     equ 7
ITEM_W          equ 2                   ; bytes: a coin, a power-up
ITEM_X          equ (LANE_W-ITEM_W)>>1  ; in its lane

; --- overlays -----------------------------------------------------------------------
OVERLAYS        equ 16
OV_SIZE         equ 8
OV_BOTTOM       equ 0                   ; world row (2)
OV_ROWS         equ 2                   ; 0 = free slot
OV_COLUMN       equ 3
OV_SPRITE       equ 4                   ; (2) its sprite
OV_WIDTH        equ 6                   ; its width in bytes (add_scenery)

ENV_URBAN       equ 0
ENV_FOREST      equ 1
SEGMENT_MIN     equ 96                  ; rows per environment: 96..159
BRIDGE_GAP_MIN  equ 80                  ; rows between bridges: 80..207
SCENERY_MARGIN  equ 6                   ; no scenery this close to a bridge/transition
CPC_PICTURE_ROWS equ 34                 ; the CPC's screen: the generator's windows

WORLD_RING      equ WS_LOW              ; 64 x 16 bytes, not on the tape
OVERLAY_LIST    equ WORLD_RING+RING_ROWS*ROW_SIZE
    assert (WORLD_RING & 255) == 0
    assert OVERLAY_LIST+OVERLAYS*OV_SIZE <= WS_LOW_END

; -----------------------------------------------------------------------------
; world_init: clears the ring, overlays and generator state.
; -----------------------------------------------------------------------------
world_init:
                ld hl,WORLD_RING
                ld de,WORLD_RING+1
                ld bc,RING_ROWS*ROW_SIZE+OVERLAYS*OV_SIZE-1
                ld (hl),0
                ldir
                ld hl,gen_state
                ld de,gen_state+1
                ld bc,GEN_STATE_SIZE-1
                ld (hl),0
                ldir
                ld hl,#ACE1
                ld (rng),hl
                ld hl,SEGMENT_MIN
                ld (seg_left),hl
                ld hl,PU_GAP_MIN            ; the first power-up
                ld (pu_gap),hl
                ld a,SPACER_START           ; an empty start, then denser
                ld (spacer_len),a
                ld (spacer_left),a
                ld hl,spacer_tick
                call spacer_step
                ld hl,BRIDGE_GAP_MIN/2
                ld (bridge_countdown),hl
                ld a,24
                ld (cross_countdown),a
                ld a,30
                ld (kiosk_countdown),a
                ld a,50
                ld (kiosk_countdown+1),a
                ld hl,ROUTE_SEG             ; the route: Kiato to Piraeus
                ld (route_left),hl
                ld a,1
                ld (station_next),a
                ret

; -----------------------------------------------------------------------------
; draw_world_row: HL = world row number, A = its slot in the ring. Rows must
; be generated in increasing order.
; -----------------------------------------------------------------------------
draw_world_row:
                push af
                push hl
                call generate_row
                pop hl
                pop af
                jp render_row

; HL = world row -> HL = its descriptor. Destroys A, DE.
desc_addr:
                ld a,l
                and RING_ROWS-1
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                ld de,WORLD_RING
                add hl,de
                ret

; -----------------------------------------------------------------------------
; random: A = next pseudo-random byte (xorshift16). Destroys nothing else.
; -----------------------------------------------------------------------------
random:
                push hl
                ld hl,(rng)
                ld a,h                      ; x ^= x << 7
                rra
                ld a,l
                rra
                xor h
                ld h,a
                ld a,l
                rra
                ld a,h                      ; x ^= x >> 9
                rra
                xor l
                ld l,a
                xor h                       ; x ^= x << 8
                ld h,a
                ld (rng),hl
                pop hl
                ret

; A = random number in 0..C-1 (C = 1..255). Destroys AF'.
random_below:
                call random
                jp mod_c

; A = A mod C (C > 0). Destroys AF' only. The CPC subtracted C until
; it went below; the same remainder here by long division: C shifted up as
; far as it stays a byte, then taken off wherever it fits, halving back
; down to C.
mod_c:
                cp c
                ret c
                push bc
                ld b,c
.up:            bit 7,b                     ; B = C * 2^k, the largest <= 255
                jr nz,.down
                sla b
                jr .up
.down:          cp b
                jr c,.less
                sub b
.less:          ex af,af'
                ld a,b
                cp c                        ; down to C itself: done
                jr z,.done
                srl b
                ex af,af'
                jr .down
.done:          ex af,af'
                pop bc
                ret

; HL = word at table HL + 2*A. Destroys A, DE.
table_entry:
                add a,a
                ld e,a
                ld d,0
                add hl,de
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ret

; =============================================================================
; generate_row: HL = world row number
; =============================================================================
generate_row:
                call gen_sides
                jp gen_track

; gen_sides: HL = world row: the first half of generate_row (difficulty,
; route, platform, environment and sides).
gen_sides:
                ld (gen_row),hl
                call desc_addr
                push hl
                pop ix
                ld b,ROW_SIZE               ; clear the descriptor
                xor a
.clear:         ld (hl),a
                inc hl
                djnz .clear

                ; difficulty 1..5 grows every 256 rows (easy), 171 (medium),
                ; 128 (hard)
                ld hl,(gen_row)
                ld d,h
                ld e,l
                srl d
                rr e                        ; DE = rows / 2
                ld a,(skill)
                or a
                ld b,a
                inc b
                ld a,h
                jr nz,.diff_add
                rra                         ; easy: every 512 rows
                jr .diff_add
.diff_more:     add hl,de
                ld a,h
                jr c,.diff_max
.diff_add:      djnz .diff_more
                inc a
                cp 6
                jr c,.diff_ok
.diff_max:      ld a,5
.diff_ok:       ld (difficulty),a

                ; empty rows between chunks: SPACER_START at first, one less
                ; every spacer_steps[skill] rows
                ld hl,spacer_tick
                dec (hl)
                call z,spacer_step

                call tick_busy_counters
                ld hl,(route_left)          ; the route: a station every
                dec hl                      ; ROUTE_SEG rows, Piraeus the 6th,
                ld a,h                      ; then from Kiato again
                or l
                jr nz,.route
                set 1,(ix+D_FLAGS)          ; F_STATION
                ld a,PLAT_ROWS              ; and its platform from here on
                ld (plat_left),a
                ld a,(route_station)
                inc a
                cp ROUTE_STATIONS-1
                jr c,.station
                xor a
.station:       ld (route_station),a
                ld hl,ROUTE_SEG
.route:         ld (route_left),hl
                ld hl,(pu_gap)              ; rows until the next power-up
                ld a,h
                or l
                jr z,.pu_due
                dec hl
                ld (pu_gap),hl
.pu_due:
                ld hl,plat_left             ; a platform: no scenery starts
                ld a,(hl)
                or a
                jr z,.no_plat
                dec (hl)
                ld (ix+D_PLAT),a
                set 4,(ix+D_FLAGS)          ; F_PLATFORM
                ld hl,busy_counters         ; cars, trees
                ld b,8
.busy:          ld (hl),1
                inc hl
                djnz .busy
.no_plat:

                ; --- environment ---
                ld a,(trans_left)
                or a
                jr z,.no_transition
                jp transition_sides
.no_transition: ld hl,(seg_left)
                dec hl
                ld (seg_left),hl
                ld a,h
                or l
                jr nz,.sides
                ld a,2                      ; next two rows: transition
                ld (trans_left),a
                call random
                and 63
                add SEGMENT_MIN
                ld l,a
                ld h,0
                ld (seg_left),hl
.sides:         ld a,(env)
                or a
                call z,urban_sides
                ld a,(env)
                or a
                ret z
                jp forest_sides

; gen_track: the second half of generate_row, for row gen_row: its track.
gen_track:
                ld hl,(gen_row)
                call desc_addr
                push hl
                pop ix
                ld hl,(bridge_countdown)
                ld a,h
                or l
                jr z,.countdown_done
                dec hl
                ld (bridge_countdown),hl
.countdown_done:
                ld a,(bridge_left)
                or a
                jp nz,bridge_row
                ld a,(chunk_left)
                or a
                jp nz,chunk_row
                ld a,(spacer_left)          ; empty rows after a chunk
                or a
                jr nz,spacer_row
                ld hl,(bridge_countdown)    ; chunk boundary: bridge due?
                ld a,h
                or l
                jp z,start_bridge
                call pick_chunk
                ld a,(spacer_len)           ; and the empty rows after it: a
                ld hl,(pu_gap)              ; power-up overdue gets a clear
                ld b,a                      ; stretch long enough for it
                ld a,h
                or l
                ld a,b
                jr nz,.spacer
                cp PU_CLEAR*2+1
                jr nc,.spacer
                ld a,PU_CLEAR*2+1
.spacer:        ld (spacer_left),a
                jp chunk_row

row_lane:       defb 0                      ; lane of the cell being placed

; --- empty track between chunks --------------------------------------------------
spacer_row:
                dec a
                ld (spacer_left),a
                ld b,a
                ld a,TILE_RAIL_A
                ld (ix+D_LANES),a
                ld (ix+D_LANES+1),a
                ld (ix+D_LANES+2),a
                ld hl,(pu_gap)              ; a power-up due and PU_CLEAR more
                ld a,h                      ; empty rows: any lane
                or l
                ret nz
                ld a,b
                cp PU_CLEAR
                ret c
                ld c,3
                call random_below
                ld (row_lane),a
                xor a                       ; (on the ground)
                ld (pu_roof),a
                ld a,(row_lane)
                call clear_behind           ; and none in the rows behind
                ret nz
                ld e,a
                ld d,0
                push ix
                pop iy
                add iy,de
                jp put_powerup

; HL = spacer_tick: reloads it, one empty row less (down to the fewest)
SPACER_START    equ 24
spacer_step:
                push hl
                ld a,(skill)
                ld hl,spacer_steps
                call add_a_hl
                ld a,(hl)
                inc hl
                inc hl
                inc hl
                ld b,(hl)                   ; B = the fewest
                pop hl
                ld (hl),a
                ld hl,spacer_len
                ld a,b
                cp (hl)
                ret nc
                dec (hl)
                ret
spacer_steps:   defb 96,40,24               ; rows per step: easy, medium, hard
                defb 8,0,0                  ; the fewest empty rows

ROUTE_SEG       equ 320                     ; rows between two stations
ROUTE_STATIONS  equ 7                       ; Kiato .. Piraeus

PU_GAP_MIN      equ 50
PU_GAP_RANGE    equ 70                      ; 50-120 rows, ~50-150 with the wait
PU_CLEAR        equ 8                       ; rows ahead and behind without an obstacle
PU_TURBO_ODDS   equ 77                      ; 30%

; A = lane: Z if none of the PU_CLEAR rows below gen_row has an obstacle
; there. Preserves A, BC, DE, HL.
clear_behind:
                push hl
                push de
                push bc
                ld c,a
                ld hl,(gen_row)
                dec hl
                call desc_addr
                ld a,D_COLL
                add a,c
                call add_a_hl               ; HL = its class in the row below
                ld de,-ROW_SIZE
                ld b,PU_CLEAR
.row:           ld a,(hl)
                call obstacle
                jr nz,.done
                add hl,de                   ; the row below, round the ring
                ld a,h
                cp WORLD_RING>>8
                jr nc,.in_ring
                ld h,(WORLD_RING+RING_ROWS*ROW_SIZE-1)>>8
.in_ring:       djnz .row
                xor a                       ; Z: all clear
.done:          ld a,c
                pop bc
                pop de
                pop hl
                ret

; A = collision byte: Z if it keeps a power-up spot clear. On the ground
; (pu_roof 0): rail and ramps. On a roof: the train (wagons, couplers, ramps).
obstacle:
                and 15
                push bc
                ld b,a
                ld a,(pu_roof)
                or a
                ld a,b
                pop bc
                jr nz,.roof
                or a
                ret z
                cp COL_GAP
                jr z,.yes
.ramps:         cp COL_RAMP_UP
                jr c,.yes                   ; 1-4: stop, signal, train, nose
                xor a                       ; ramps (and couplers on a roof)
                ret
.roof:          cp COL_TRAIN
                ret z
                jr .ramps                   ; 0-4: off the train
.yes:           or #80                      ; NZ
                ret
pu_roof:        defb 0                      ; the power-up spot being checked

; IY = descriptor + lane, (row_lane) = lane: a power-up there
put_powerup:
                call random                 ; the kind
                cp PU_TURBO_ODDS
                ld a,ITEM_TURBO
                jr c,.kind
.other:         call random
                and 7
                cp 5
                jr nc,.other
                ld hl,pu_kinds
                call add_a_hl
                ld a,(hl)
.kind:          ld (iy+D_ITEM),a
                call spawn_item
                ld c,PU_GAP_RANGE+1         ; (finding a safe spot adds some)
                call random_below
                add PU_GAP_MIN&#FF
                ld l,a
                ld h,0
                ld (pu_gap),hl
                ret
pu_kinds:       defb ITEM_MAGNET,ITEM_SLOW,ITEM_SPRING,ITEM_HELMET,ITEM_TICKET

; A = lane -> A = its first byte column
lane_column:
                add a,a
                add a,a
                add COL_LANE1
                ret

; A = item, (row_lane) = lane: registers the item overlay
spawn_item:
                ld c,a
                ld a,(row_lane)
                call lane_column
                add ITEM_X
                ld b,a                      ; B = its column
                ld a,c
                cp ITEM_COIN
                jr nz,.powerup
                ld c,b
                ld hl,gfx_items_coin0
                ld a,1
                jp add_overlay
.powerup:       add IDX_ITEMS_PU_MAGNET-2   ; item 2.. -> power-up frames
                ld hl,gfx_items_table
                push bc
                call table_entry
                pop bc
                ld c,b
                ld a,2
                jp add_overlay

; --- bridges ------------------------------------------------------------------------
start_bridge:
                call random
                and 127
                add BRIDGE_GAP_MIN
                ld l,a
                ld h,0
                ld (bridge_countdown),hl
                ; road bridge in the city half of the time, footbridge otherwise
                ld hl,footbridge_rows
                ld a,(env)
                or a
                jr nz,.chosen
                call random
                rra
                jr nc,.chosen
                ld hl,roadbridge_rows
.chosen:        ld a,(hl)
                inc hl
                ld (bridge_left),a
                ld (bridge_ptr),hl
                ; fall through

bridge_row:
                ld hl,(bridge_ptr)
                ld a,(hl)
                inc hl
                ld (bridge_ptr),hl
                ld (ix+D_LEFT),a
                ld a,(ix+D_FLAGS)
                or F_BRIDGE
                ld (ix+D_FLAGS),a
                ld a,IDX_TRACK_RAIL_A
                ld (ix+D_LANES),a
                ld (ix+D_LANES+1),a
                ld (ix+D_LANES+2),a
                ld hl,bridge_left
                dec (hl)
                ret

; bottom to top: shadow, then the deck rows
footbridge_rows:
                defb 4
                defb IDX_BRIDGES_FOOTBRIDGE_SHADOW,IDX_BRIDGES_FOOTBRIDGE_0
                defb IDX_BRIDGES_FOOTBRIDGE_1,IDX_BRIDGES_FOOTBRIDGE_2
roadbridge_rows:
                defb 7
                defb IDX_BRIDGES_ROADBRIDGE_SHADOW,IDX_BRIDGES_ROADBRIDGE_0
                defb IDX_BRIDGES_ROADBRIDGE_1,IDX_BRIDGES_ROADBRIDGE_2,IDX_BRIDGES_ROADBRIDGE_3
                defb IDX_BRIDGES_ROADBRIDGE_4,IDX_BRIDGES_ROADBRIDGE_5

; --- busy counters: rows until a car lane / tree spot / side feature is free ------
tick_busy_counters:
                ld hl,busy_counters
                ld b,BUSY_COUNT
.next:          ld a,(hl)
                or a
                jr z,.zero
                dec (hl)
.zero:          inc hl
                djnz .next
                ret

; scenery may only start where it cannot reach a transition or a bridge
; returns NZ if allowed for C rows
scenery_allowed:
                ld a,(trans_left)
                or a
                jr nz,.no
                ld a,(bridge_left)
                or a
                jr nz,.no
                ld hl,(seg_left)
                ld a,h
                or a
                jr nz,.seg_ok
                ld a,l
                sub SCENERY_MARGIN
                jr c,.no
                cp c
                jr c,.no
.seg_ok:        ld hl,(bridge_countdown)
                ld a,h
                or a
                jr nz,.yes
                ld a,l
                sub SCENERY_MARGIN
                jr c,.no
                cp c
                jr c,.no
.yes:           or 1
                ret
.no:            xor a
                ret

; =============================================================================
; Sides
; =============================================================================

; --- avenue ---------------------------------------------------------------------
urban_sides:
                ; base: dashed lane lines every 16 lines (road_a, road_b)
                ld a,(gen_row)
                and 1
                add a,a                     ; road_a = 0, road_b = 2
                ld (ix+D_LEFT),a
                inc a
                ld (ix+D_RIGHT),a

                ; zebra crossing over both sides
                ld a,(cross_phase)
                or a
                jr nz,.crossing
                ld hl,cross_countdown
                dec (hl)
                jr nz,.kiosks
                call random
                and 63
                add 40
                ld (hl),a
                ld a,2
                ld (cross_phase),a
.crossing:      ld hl,cross_phase           ; phase 2 = bottom row, 1 = top row
                ld a,(hl)
                dec (hl)
                cp 2
                ld a,IDX_URBAN_ROAD_CROSS_0
                jr z,.cross_tile
                ld a,IDX_URBAN_ROAD_CROSS_1
.cross_tile:    ld (ix+D_LEFT),a
                inc a
                ld (ix+D_RIGHT),a
                jr .cars

                ; kiosks on the outer lane, each side on its own
.kiosks:        ld b,0
                call .kiosk
                ld b,1
                call .kiosk

.cars:          ld b,0
                call spawn_car
                ld b,1
                jp spawn_car

; B = side
.kiosk:         ld hl,kiosk_phase
                call add_b_hl
                ld a,(hl)
                or a
                jr nz,.kiosk_row
                ld hl,kiosk_countdown
                call add_b_hl
                dec (hl)
                ret nz
                ld (hl),40                  ; retry later if the outer lane is busy
                push hl
                ld a,b                      ; outer car lane of this side
                add a,a
                add a,b
                ld hl,car_busy
                call add_a_hl
                ld a,(hl)
                or a
                pop de                      ; DE = countdown
                ret nz
                ld (hl),3                   ; keep cars away from the kiosk
                call random
                and 127
                add 60
                ld (de),a
                ld hl,kiosk_phase
                call add_b_hl
                ld (hl),2
.kiosk_row:     ld a,(hl)                   ; 2 = bottom row, 1 = top row
                dec (hl)
                cp 2
                ld a,IDX_URBAN_ROAD_KIOSK_0
                jr z,.kiosk_tile
                ld a,IDX_URBAN_ROAD_KIOSK_1
.kiosk_tile:    bit 0,b
                jr z,.left
                inc a                       ; mirrored copy
                ld (ix+D_RIGHT),a
                ret
.left:          ld (ix+D_LEFT),a
                ret

; HL += B / HL += A. Destroy A.
add_b_hl:
                ld a,b
add_a_hl:
                add a,l
                ld l,a
                ret nc
                inc h
                ret

; B = side: maybe start a vehicle in a free lane of that side
spawn_car:
                call random
                and 7
                ret nz
                push bc
                ld c,4                      ; longest vehicle: 4 rows
                call scenery_allowed
                pop bc
                ret z
                ld c,3
                call random_below           ; lane 0..2
                ld c,a
                ld a,b                      ; busy index = side*3 + lane
                add a,a
                add a,b
                add a,c
                ld e,a
                ld d,0
                ld hl,car_busy
                add hl,de
                ld a,(hl)
                or a
                ret nz
                push hl                     ; HL = busy counter
                ld hl,car_columns           ; its column
                add hl,de
                ld a,(hl)
                ld (.column),a
                ; vehicle: 1/8 bus, 1/8 trolley, else a car (2 rows)
                call random
                and 7
                ld c,4
                ld e,IDX_URBAN_OV_BUS
                jr z,.picked
                dec a
                ld e,IDX_URBAN_OV_TROLLEY
                jr z,.picked
                and 3
                add a,a                     ; car frames are pairs (original, mirror)
                ld e,a
                ld c,2
.picked:        ld a,e
                bit 0,b
                jr z,.unmirrored
                inc a                       ; right side: mirrored copy
.unmirrored:    ld e,a
                pop hl
                call random
                and 3
                add c
                inc a
                ld (hl),a                   ; busy for rows + gap
                ld a,e
                ld hl,gfx_urban_ov_table
                call table_entry
                ld a,(.column)
                ld b,c
                ld c,a
                ld a,b
                jp add_scenery
.column:        defb 0

; the avenue's lanes, outer to inner: left side, then right side
car_columns:    defb COL_LEFT,COL_LEFT+2,COL_LEFT+4
                defb COL_RIGHT+4,COL_RIGHT+2,COL_RIGHT

; --- transition rows (2): forest tile set ------------------------------------------
transition_sides:
                ld a,(ix+D_FLAGS)
                or F_FOREST
                ld (ix+D_FLAGS),a
                ld a,(env)
                or a
                ld a,IDX_FOREST_TRANS_URBAN_FOREST_0
                jr z,.from_urban
                ld a,IDX_FOREST_TRANS_FOREST_URBAN_0
.from_urban:    ld b,a
                ld a,(trans_left)           ; 2 = bottom row, 1 = top row
                cp 2
                ld a,b
                jr z,.tile
                add 2                       ; next frame (pairs with mirrors)
.tile:          ld (ix+D_LEFT),a
                inc a
                ld (ix+D_RIGHT),a
                ld hl,trans_left
                dec (hl)
                ret nz
                ld a,(env)                  ; transition done
                xor 1
                ld (env),a
                ret

; -----------------------------------------------------------------------------
; add_scenery: as add_overlay, for scenery (cars, trees), unless the
; overlays in the row (items too) would grow wider than SCENERY_W_MAX bytes:
; render_row draws them all with the new row.
; -----------------------------------------------------------------------------
SCENERY_W_MAX   equ 8

add_scenery:
                push af
                ld a,(scenery_width)
                add a,(hl)
                cp SCENERY_W_MAX+1
                jr c,.room
                pop af                      ; too wide: not this time
                ret
.room:          pop af
                ; fall through

; -----------------------------------------------------------------------------
; add_overlay: HL = sprite, C = column, A = rows; bottom = gen_row. Silently
; dropped if the list is full.
; -----------------------------------------------------------------------------
add_overlay:
                ld b,a
                push hl
                ld hl,OVERLAY_LIST+OV_ROWS
                ld de,OV_SIZE
                ld a,OVERLAYS
.find:          ex af,af'
                ld a,(hl)
                or a
                jr z,.free
                add hl,de
                ex af,af'
                dec a
                jr nz,.find
                pop hl
                ret
.free:          ld (hl),b                   ; rows
                inc hl
                ld (hl),c                   ; column
                inc hl
                pop de
                ld (hl),e                   ; sprite
                inc hl
                ld (hl),d
                inc hl
                ld a,(de)
                ld (hl),a                   ; its width
                push hl
                ld hl,scenery_width
                add a,(hl)
                ld (hl),a
                pop hl
                ld de,-OV_WIDTH
                add hl,de                   ; back to the slot start
                ld de,(gen_row)
                ld (hl),e
                inc hl
                ld (hl),d
                ret

; =============================================================================
; render_row: HL = world row, A = its slot: its pixels and attributes into the
; ring, then the slices of the overlays that fall in it. Also in parts, one
; at a time: render_part.
; =============================================================================
render_row:
                push hl
                push af
                call render_part
                pop bc
                pop hl
                ld a,b
                jr nc,render_row
                ret

; render_part: HL = world row, A = its slot: the next part of drawing it,
; by draw_phase: 0 the tiles' first four lines (a bridge row: all of it),
; 1 the other four and the attributes, 2 an overlay's slice (as long as
; there are), 3 done (ring_done): C, and draw_phase is 0 again.
render_part:
                ld b,a
                ld a,(rr_mine)              ; rr_* still this row's?
                or a
                jr z,.setup
                ld de,(rr_row)
                or a
                sbc hl,de
                add hl,de
                jr nz,.setup
                ld ix,(rr_desc)
                jr .phase
.setup:         ld a,b
                call render_setup
.phase:         ld a,(draw_phase)
                or a
                jr z,.top
                dec a
                jr z,.bottom
                dec a
                jr z,.slices
.done:          xor a                       ; done
                ld (draw_phase),a
                ld a,(rr_slot)
                call ring_done
                scf
                ret
.top:           call render_tiles
                ld a,1
                bit 7,(ix+D_FLAGS)          ; a bridge: whole already
                jr z,.phase_set
.to_slices:     ld iy,OVERLAY_LIST          ; the first slice, if any, known
                call ov_find                ; (job_bound looks at it)
                ld (ov_next),iy
                ld a,2
                jr nz,.phase_set
                inc a                       ; none: ring_done next
.phase_set:     ld (draw_phase),a
                or a
                ret
.bottom:        call render_tiles_bottom
                jr .to_slices
.slices:        call draw_overlays_step
                ret nz                      ; (NC) more to come
                jr nc,.done                 ; none: ring_done now
                ld a,3                      ; the last: ring_done next
                jr .phase_set

; HL = world row, A = slot: rr_*, IX = its descriptor.
render_setup:
                ld (rr_slot),a
                ld (rr_row),hl
                call desc_addr
                ld (rr_desc),hl
                push hl
                pop ix
                ld a,1
                ld (rr_mine),a
                ld a,(rr_slot)
                call slot_addr
                ld (rr_dest),hl
                ld a,(rr_slot)
                call attr_slot_addr
                ld (rr_attr),hl
                ret

; render_tiles: rr_* set up: the tiles' first four lines (a bridge: the
; whole row); render_tiles_bottom the rest of them.
render_tiles:
    assert RING_SPLIT == COL_LANE1+LANE_W/2 && COL_RIGHT == COL_LANE1+3*LANE_W
                bit 7,(ix+D_FLAGS)
                jr z,.normal
                ld a,(ix+D_LEFT)            ; bridge: one tile, the whole row
                ld hl,gfx_bridges_table
                call table_entry
                jp bridge_tile

.normal:        ld hl,gfx_urban_table      ; the five tiles: their pointers
                bit 0,(ix+D_FLAGS)          ; in a ring line's order
                jr z,.set
                ld hl,gfx_forest_table
.set:           push hl
                ld a,(ix+D_LEFT)
                call table_entry
                ld (rt_left),hl
                pop hl
                ld a,(ix+D_RIGHT)
                call table_entry
                ld (rt_right),hl
                ld hl,gfx_track_table
                ld a,(ix+D_LANES)
                call table_entry
                ld (rt_lane1),hl
                ld hl,gfx_track_table
                ld a,(ix+D_LANES+1)
                call table_entry
                ld (rt_lane2),hl
                ld hl,gfx_track_table
                ld a,(ix+D_LANES+2)
                call table_entry
                ld (rt_lane3),hl
                ld de,(rr_dest)             ; ring lines one after the other
                ld bc,ROW_LINES/4*256+255   ; (C: the LDIs never borrow from B)
                call rt_lines
                ld (rt_dest),de
                ret

render_tiles_bottom:
                ld de,(rt_dest)
                ld bc,ROW_LINES/4*256+255
                call rt_lines
                jp rt_attrs

; B pairs of lines, DE in the ring: an even line is columns 8-23 (half of
; the first lane on), then 0-7; an odd line in column order (video.asm).
rt_lines:
.pair:          ld hl,(rt_lane1)            ; even: lane 1's right half
                inc hl
                inc hl
                ldi
                ldi
                ld hl,(rt_lane2)
                repeat LANE_W
                ldi
                rend
                ld (rt_lane2),hl
                ld hl,(rt_lane3)
                repeat LANE_W
                ldi
                rend
                ld (rt_lane3),hl
                ld hl,(rt_right)
                repeat SIDE_W
                ldi
                rend
                ld (rt_right),hl
                ld hl,(rt_left)
                repeat SIDE_W
                ldi
                rend
                ld (rt_left),hl
                ld hl,(rt_lane1)            ; and its left half
                ldi
                ldi
                inc hl
                inc hl
                ld (rt_lane1),hl
                ld hl,(rt_left)             ; odd
                repeat SIDE_W
                ldi
                rend
                ld (rt_left),hl
                ld hl,(rt_lane1)
                repeat LANE_W
                ldi
                rend
                ld (rt_lane1),hl
                ld hl,(rt_lane2)
                repeat LANE_W
                ldi
                rend
                ld (rt_lane2),hl
                ld hl,(rt_lane3)
                repeat LANE_W
                ldi
                rend
                ld (rt_lane3),hl
                ld hl,(rt_right)
                repeat SIDE_W
                ldi
                rend
                ld (rt_right),hl
                dec b
                jp nz,.pair
                ret

rt_attrs:       ld de,(rr_attr)             ; the attributes, in column order
                ld hl,(rt_left)             ; (each tile's follow its lines)
                repeat SIDE_W
                ldi
                rend
                ld hl,(rt_lane1)
                repeat LANE_W
                ldi
                rend
                ld hl,(rt_lane2)
                repeat LANE_W
                ldi
                rend
                ld hl,(rt_lane3)
                repeat LANE_W
                ldi
                rend
                ld hl,(rt_right)
                repeat SIDE_W
                ldi
                rend
                ld a,(ix+D_PLAT)            ; a station's platform over the sides
                or a
                call nz,platform_strip
                ret

; A = D_PLAT: the platform's row on both sides, inside the avenue or forest
PLAT_ROWS       equ GFX_PLATFORM_SEQ_LEN
PLAT_W          equ 3
platform_strip:
                ld hl,gfx_platform_seq-1
                call add_a_hl
                ld a,(hl)                   ; its kind, #FF none
                cp #FF
                ret z
                add a,a                     ; left, then the mirrored right
                push af
                ld hl,gfx_platform_table
                call table_entry
                ld b,COL_LANE1-PLAT_W
                ld c,PLAT_W
                call blit_tile
                pop af
                inc a
                ld hl,gfx_platform_table
                call table_entry
                ld b,COL_RIGHT
                ld c,PLAT_W
                jp blit_tile

; -----------------------------------------------------------------------------
; blit_tile: HL = a tile (its 8 lines of C bytes, then C attributes), B =
; byte column, C = width 1-24: into the row being rendered (rr_dest,
; rr_attr). An even ring line has columns 8-23 first: a tile across column
; 8 goes there in two pieces. Destroys AF, BC, DE, HL.
; -----------------------------------------------------------------------------
blit_tile:
                ld a,b
                ld (bt_col),a
                ld a,c
                ld (bt_w),a
                ld a,b                      ; even lines: where, and how many
                sub RING_SPLIT              ; before the line's end
                jr c,.left
                ld (bt_even),a              ; all of it from column 8 on
                ld a,c
                ld (bt_n1),a
                xor a
                jr .n2
.left:          add a,PLAY_W                ; columns 0-7 are at 16-23
                ld (bt_even),a
                ld a,RING_SPLIT
                sub b                       ; those before column 8
                cp c
                jr c,.split
                ld a,c
.split:         ld (bt_n1),a
                ld b,a
                ld a,c
                sub b                       ; the rest at the line's start
.n2:            ld (bt_n2),a
                ld de,(rr_dest)
                ld a,ROW_LINES/2
.pair:          ld (bt_base),de
                push af
                ld a,(bt_even)              ; even line
                call add_a_de
                ld a,(bt_n1)
                ld c,a
                ld b,0
                ldir
                ld a,(bt_n2)
                or a
                jr z,.odd
                ld de,(bt_base)
                ld c,a
                ldir
.odd:           ld de,(bt_base)             ; odd line
                ld a,(bt_col)
                add a,PLAY_W
                call add_a_de
                ld a,(bt_w)
                ld c,a
                ld b,0
                ldir
                ld de,(bt_base)             ; two lines down
                ld a,2*PLAY_W
                call add_a_de
                pop af
                dec a
                jr nz,.pair
                ld de,(rr_attr)             ; the attributes
                ld a,(bt_col)
                call add_a_de
                ld a,(bt_w)
                ld c,a
                ld b,0
                ldir
                ret
bt_col:         defb 0
bt_w:           defb 0
bt_even:        defb 0                      ; an even line: where it starts
bt_n1:          defb 0                      ;  and how many there
bt_n2:          defb 0                      ;  and at the line's start
bt_base:        defw 0

; HL = a bridge row (24 bytes a line, then 24 attributes) into the row
; being rendered, in the ring's order.
bridge_tile:
                ld de,(rr_dest)
                ld a,ROW_LINES/2
.pair:          ld bc,RING_SPLIT            ; even: columns 8-23, then 0-7
                add hl,bc
                ld bc,PLAY_W-RING_SPLIT
                ldir
                ld bc,-PLAY_W
                add hl,bc
                ld bc,RING_SPLIT
                ldir
                ld bc,PLAY_W-RING_SPLIT
                add hl,bc
                ld bc,PLAY_W                ; odd: as it is
                ldir
                dec a
                jr nz,.pair
                ld de,(rr_attr)
                ld bc,PLAY_W
                ldir
                ret

; DE += A. Destroys A.
add_a_de:
                add a,e
                ld e,a
                ret nc
                inc d
                ret


; --- slices of the active overlays that fall in rr_row ----------------------------
draw_overlays:
                ld hl,OVERLAY_LIST
                ld (ov_next),hl
.step:          call draw_overlays_step
                jr nz,.step
                ret

; draw_overlays_step: the overlay at ov_next on (ov_find) drawn, then the
; next one found, so that a row's last slice ends its slices too:
;   NZ, NC - drawn, another to come (ov_next)
;   Z, C   - drawn, the last
;   Z, NC  - none at all
; IX = the descriptor.
OVERLAY_END     equ OVERLAY_LIST+OVERLAYS*OV_SIZE
draw_overlays_step:
                ld iy,(ov_next)
                call ov_find
                ret z                       ; (NC)
                call draw_overlay_slice
                set 6,(ix+D_FLAGS)
                ld a,(draw_overlays.above)
                or a
                call z,.free_it             ; its top row: free the slot
                ld de,OV_SIZE
                add iy,de
                call ov_find
                ld (ov_next),iy
                scf
                ret z                       ; the last
                ccf
                ret                         ; (NZ, NC)
.free_it:       ld (iy+OV_ROWS),0
                ld a,(scenery_width)
                sub (iy+OV_WIDTH)
                ld (scenery_width),a
                ret

; ov_find: from overlay IY on, the first with a slice in row rr_row: NZ, IY
; at it, draw_overlays.above = its rows above this one; Z if none. Frees
; those wholly below the row on the way. Destroys AF, BC, DE, HL.
ov_find:
                push iy
                pop hl
                ld a,OVERLAY_END & #FF      ; B = slots left (the list is
                sub l                       ; under 256 bytes)
                jr z,.end
                rrca
                rrca
                rrca
                ld b,a
                inc hl
                inc hl                      ; HL at OV_ROWS
                ld de,OV_SIZE
.slot:          ld a,(hl)                   ; free slots: 42 T each
                or a
                jr nz,.in
.next:          add hl,de
                djnz .slot
.end:           ld iy,OVERLAY_END
                xor a                       ; (Z)
                ret
.in:            push hl
                push bc
                push hl
                pop iy
                dec iy
                dec iy
                ; top = bottom + rows - 1; slice if bottom <= row <= top
                ld hl,(rr_row)
                ld c,(iy+OV_BOTTOM)
                ld b,(iy+OV_BOTTOM+1)
                or a
                sbc hl,bc                   ; HL = row - bottom
                jr c,.skip
                ld a,h
                or a
                jr nz,.free
                ld a,l
                cp (iy+OV_ROWS)
                jr nc,.free
                ; rows above this one inside the overlay = rows-1-(row-bottom)
                ld b,a
                ld a,(iy+OV_ROWS)
                dec a
                sub b
                ld (draw_overlays.above),a
                pop bc
                pop hl
                or 1                        ; (NZ)
                ret
.free:          call draw_overlays_step.free_it
.skip:          pop bc
                pop hl
                jr .next
draw_overlays.above:
                defb 0
ov_next:        defw 0                      ; the next overlay to look at

; IY = overlay, (draw_overlays.above) = rows above this one inside it: its
; lines in this row, masked, and its ink on the cells it covers. A sprite's
; lines are spans (src/sprite.asm); slice k of them starts where the word at
; the sprite - 2k says (src/data/gfx.asm).
draw_overlay_slice:
                ld l,(iy+OV_SPRITE)
                ld h,(iy+OV_SPRITE+1)
                inc hl
                ld a,(draw_overlays.above)
                add a,a
                add a,a
                add a,a                     ; first line of the slice
                ld b,a
                ld a,(hl)                   ; height (lines)
                sub b
                ret c                       ; sprite shorter than its rows
                ret z
                cp ROW_LINES
                jr c,.count
                ld a,ROW_LINES
.count:         ld c,a                      ; C = lines
                inc hl
                ld a,(hl)                   ; its ink, #FF none
                ld (.ink),a
                inc hl                      ; slice 0: here
                ld a,(draw_overlays.above)
                or a
                jr z,.at
                ld l,(iy+OV_SPRITE)         ; slice k: sprite + (sprite - 2k)
                ld h,(iy+OV_SPRITE+1)
                push hl
                add a,a
                cpl
                inc a                       ; -2k
                ld e,a
                ld d,#FF
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                pop hl
                add hl,de
.at:            ex de,hl                    ; DE = its lines
                ld hl,(rr_dest)
                ld (.base),hl
                ld a,(iy+OV_COLUMN)
                ld (.col),a
                xor a
                ld (.odd),a
                ld l,(iy+OV_SPRITE)         ; across column 8 (lane 1's
                ld h,(iy+OV_SPRITE+1)       ; items)? then line by line
                ld a,(.col)
                cp RING_SPLIT
                jr nc,.whole_right
                add a,(hl)
                cp RING_SPLIT+1
                jr nc,.line
                ld a,(.col)                 ; all before column 8: an even
                add a,PLAY_W-RING_SPLIT     ; line has it 16 further on
                jr .fast
.whole_right:   sub RING_SPLIT              ; all from column 8 on: 8 back
.fast:          ld (.even_at),a
                srl c                       ; pairs of lines (a slice is 8
.pair:          ld a,(.even_at)             ; or 4 of them)
                call .span
                ld a,(.col)
                add a,PLAY_W
                call .span
                ld hl,(.base)
                ld a,2*PLAY_W
                call add_a_hl
                ld (.base),hl
                dec c
                jr nz,.pair
                jp .ink_cells
; A = where in the line pair its columns start: the line's span there
.span:          ld hl,(.base)
                ex de,hl
                add a,(hl)                  ; + skip
                inc hl
                ld b,(hl)                   ; count
                inc hl
                ex de,hl
                call add_a_hl
                inc b
                dec b
                ret z
                jr .bytes
.line:          ld a,(de)                   ; skip
                inc de
                ld hl,.col
                add a,(hl)
                ld b,a                      ; B = its first column
                ld a,(de)                   ; count
                inc de
                or a
                jr z,.next
                ld (.n),a
                ld hl,(.base)
                ld a,(.odd)
                or a
                ld a,b
                jr nz,.at_col               ; an odd line: in column order
                sub RING_SPLIT
                jr nc,.at_col               ; even, from column 8: there
                add a,PLAY_W                ; even, before it: 16 on, up to
                ld (.first),a               ; column 8
                ld a,RING_SPLIT
                sub b
                ld b,a                      ; B = those before column 8
                ld a,(.n)
                cp b
                jr nc,.cut
                ld b,a
.cut:           sub b
                ld (.n),a                   ; the rest after them
                ld a,(.first)
                call add_a_hl
                call .bytes
                ld a,(.n)
                or a
                jr z,.next
                ld hl,(.base)               ; at the line's start
                jr .rest
.at_col:        call add_a_hl
                ld a,(.n)
.rest:          ld b,a
                call .bytes
.next:          ld hl,(.base)               ; a line down
                ld a,PLAY_W
                call add_a_hl
                ld (.base),hl
                ld a,(.odd)
                xor 1
                ld (.odd),a
                dec c
                jr nz,.line
                jr .ink_cells
; B bytes: DE = their (mask, data) pairs, HL = the ring
.bytes:         ex de,hl
.byte:          ld a,(de)                   ; (ring AND mask) OR data
                and (hl)
                inc hl
                or (hl)
                inc hl
                ld (de),a
                inc de
                djnz .byte
                ex de,hl
                ret
.base:          defw 0
.even_at:       defb 0
.col:           defb 0
.odd:           defb 0
.n:             defb 0
.first:         defb 0
.ink_cells:
                ld a,(.ink)                 ; its ink on its cells
                cp #FF
                ret z
                ld b,a
                ld l,(iy+OV_SPRITE)
                ld h,(iy+OV_SPRITE+1)
                ld c,(hl)                   ; width
                ld hl,(rr_attr)
                ld a,(iy+OV_COLUMN)
                call add_a_hl
.attr:          ld a,(hl)                   ; the paper stays, and its BRIGHT
                and #78                     ; unless it is black (a bright
                bit 5,a                     ; coin would light a green roof)
                jr nz,.paper
                bit 4,a
                jr nz,.paper
                bit 3,a
                jr nz,.paper
                ld a,b                      ; black paper: the ink as it is
                jr .set
.paper:         ld d,a
                ld a,b
                and 7
                or d
.set:           ld (hl),a
                inc hl
                dec c
                jr nz,.attr
                ret
.ink:           defb 0

rt_dest:        defw 0                      ; render_tiles: where it got to
rt_left:        defw 0                      ;  and the tiles' next line
rt_lane1:       defw 0
rt_lane2:       defw 0
rt_lane3:       defw 0
rt_right:       defw 0
rr_slot:        defb 0
rr_mine:        defb 0                      ; rr_* are render_part's row's
rr_desc:        defw 0
rr_row:         defw 0
rr_dest:        defw 0                      ; the row's first byte in the ring
rr_attr:        defw 0                      ; and its attribute line

; -----------------------------------------------------------------------------
; Forest sides: ground, paths, fences and the trees, bushes and rocks.
; (chunk_pick.asm's forest_sides_c5 on the CPC)
; -----------------------------------------------------------------------------
forest_sides:
                ld a,(ix+D_FLAGS)
                or F_FOREST
                ld (ix+D_FLAGS),a
                ld b,0
                call .side
                ld b,1
                call .side
                ld b,0
                call spawn_tree
                ld b,1
                jp spawn_tree

; B = side
.side:          ld e,b
                ld d,0
                ld hl,path_left
                add hl,de
                ld a,(hl)
                or a
                jr z,.no_path
                dec (hl)
                ld a,IDX_FOREST_PATH
                jr .store
.no_path:       ld hl,fence_left
                add hl,de
                ld a,(hl)
                or a
                jr z,.no_fence
                dec (hl)
                ld a,IDX_FOREST_FENCE
                jr .store
.no_fence:      call random                 ; start a path or a fence now and then
                and 31
                jr nz,.ground
                call random
                and 3
                add 3
                ld c,a
                call random
                rra
                ld hl,path_left
                jr c,.run
                ld hl,fence_left
.run:           add hl,de
                ld (hl),c
.ground:        call random
                and 2                       ; ground_a = 0, ground_b = 2
.store:         bit 0,b
                jr z,.left
                inc a
                ld (ix+D_RIGHT),a
                ret
.left:          ld (ix+D_LEFT),a
                ret

; B = side: maybe plant a tree / bush / rock
spawn_tree:
                ld e,b
                ld d,0
                ld hl,tree_busy
                add hl,de
                ld a,(hl)
                or a
                ret nz
                call random
                and 3
                ret nz
                push hl
                push bc
                ld c,3
                call scenery_allowed
                pop bc
                pop hl
                ret z
                push hl
                ld c,5
                call random_below
                ld e,a
                ld d,0
                ld hl,tree_info             ; width (bytes), rows
                add hl,de
                add hl,de
                ld a,(hl)
                ld (.width),a
                inc hl
                ld a,(hl)
                ld (.rows),a
                pop hl
                inc a                       ; busy rows + 1
                ld (hl),a
                ; column: anywhere it fits in the side
                ld a,(.width)
                neg
                add SIDE_W+1
                ld c,a                      ; choices
                call random_below
                bit 0,b
                jr z,.col
                add COL_RIGHT
.col:           ld c,a
                push bc
                ld a,e
                ld hl,gfx_forest_ov_table
                call table_entry
                pop bc
                ld a,(.rows)
                jp add_scenery
.width:         defb 0
.rows:          defb 0

tree_info:      defb 3,3, 4,3, 2,3, 2,1, 2,1    ; pine, oak, cypress, bush, rock

; --- weighted chunk choice and its rows: src/chunk_pick.asm ------------------------

; -----------------------------------------------------------------------------
; stations: once a game frame. When the runner reaches a station row (and
; the bell rings) its name is written on the track; Piraeus gives 1000
; points and the route starts over.
; -----------------------------------------------------------------------------
stations:
                ld hl,(feet_row)
                ld de,(station_seen)
                or a
                sbc hl,de
                ret z
                add hl,de
                ld (station_seen),hl
                call desc_addr
                bit 1,(hl)                  ; F_STATION
                ret z
                ld a,(station_next)         ; 1 Corinth .. 6 Piraeus
                ld b,a
                inc a
                cp ROUTE_STATIONS
                jr c,.next
                ld a,1
.next:          ld (station_next),a
                ld a,SFX_SIGNAL
                ld (sfx_request),a
                ld a,b
                cp ROUTE_STATIONS-1
                call z,piraeus_bonus
                ld a,b
                add a,LABEL_STATION-1
                jp make_label

piraeus_bonus:                              ; 1000 points
                push bc
                ld hl,score+1
                ld a,(hl)
                add a,#10
                daa
                ld (hl),a
                inc hl
                ld a,(hl)
                adc a,0
                daa
                ld (hl),a
                pop bc
                ret nc
                jp score_add.full

station_seen:   defw 0                  ; the runner's row when last checked
station_next:   defb 1                  ; the next station's number

; --- generator state (cleared by world_init) ---------------------------------------
gen_state:
plat_left:      defb 0                  ; rows of the station's platform left
scenery_width:  defb 0                  ; bytes of the active overlays (add_scenery)
rng:            defw 0
gen_row:        defw 0
pu_gap:         defw 0                  ; rows until the next power-up
spacer_len:     defb 0                  ; empty rows after each chunk
spacer_left:    defb 0                  ; empty rows still to come
spacer_tick:    defb 0                  ; rows until spacer_len shrinks
difficulty:     defb 0
env:            defb 0
seg_left:       defw 0
trans_left:     defb 0
chunk_left:     defb 0
chunk_ptr:      defw 0
bridge_left:    defb 0
bridge_ptr:     defw 0
bridge_countdown: defw 0
cross_countdown: defb 0
cross_phase:    defb 0
kiosk_countdown: defb 0,0
kiosk_phase:    defb 0,0
path_left:      defb 0,0
fence_left:     defb 0,0
route_left:     defw 0                  ; rows to the next station
route_station:  defb 0                  ; stations passed on this lap (0-5)
busy_counters:
car_busy:       defs 6
tree_busy:      defs 2
BUSY_COUNT      equ $-busy_counters
GEN_STATE_SIZE  equ $-gen_state
