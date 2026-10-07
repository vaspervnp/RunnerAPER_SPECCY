; =============================================================================
; Track chunks (the CPC's src/chunk_pick.asm, without the moving trains).
;
; pick_chunk: the next track chunk, weighted random among the chunks the
; difficulty and the environment allow (src/data/chunks.asm). One pass
; works out the weights into chunk_weights, the second only subtracts.
; Each chunk then gets a random lane order (any of the 6, or only as it is /
; mirrored when it has trains side by side: hops between roofs) and a random
; livery for its trains, so the same chunk looks and plays differently.
; =============================================================================
pick_chunk:
                ld hl,(gen_row)             ; a new game: no obstacles behind
                ld de,SPACER_START+1
                or a
                sbc hl,de
                call c,easy_reset
                ld a,(env)                  ; weights per environment: those
                call env_cache              ; of an earlier difficulty will do
                ld (.table),de              ; (chunk_prewarm brings them up to
                ld a,(hl)                   ; date in a light frame)
                inc a
                jr nz,.weighed
                push hl
                ld a,(env)                  ; none yet: now
                call weigh_env
                pop hl
.weighed:       inc hl
                ld c,(hl)                   ; C = their total
.pick:          call random_below           ; A = 0 .. total-1
                ld hl,(.table)
                ld de,chunk_table
                ld b,CHUNK_COUNT
.find:          sub (hl)
                jr c,.found
                inc hl
                inc de
                inc de
                djnz .find
                ld de,chunk_table           ; (rounding safety) chunk 0
.found:         ex de,hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld a,(hl)
                ld (chunk_left),a
                inc hl
                inc hl
                inc hl
                ld a,(hl)                   ; env | CHUNK_SIDE_BY_SIDE | CHUNK_RAMP
                inc hl
                ld (chunk_ptr),hl
                ld b,a
                and CHUNK_RAMP
                ld (roofs_reachable),a      ; power-ups on its roofs too
                ld a,b
                ld c,6                      ; lane order: any
                and CHUNK_SIDE_BY_SIDE
                jr z,.order
                ld c,2                      ; as it is or mirrored
.order:         call random_below
                ld b,a
                add a,a
                add a,b
                ld hl,lane_orders
                call add_a_hl
                ld de,chunk_lanes
                ld bc,3
                ldir
                ld hl,chunk_lanes           ; and back: chunk_src[chunk_lanes[k]] = k
                ld b,0
.back:          ld a,(hl)
                push hl
                ld hl,chunk_src
                call add_a_hl
                ld (hl),b
                pop hl
                inc hl
                inc b
                ld a,b
                cp 3
                jr nz,.back
                ld c,3                      ; livery shift 0-2: its livery_tiles
                call random_below
                rrca
                rrca
                ld (livery),a               ; 0, 64, 128
                ret

.table:         defw 0                      ; chunk_weights of this environment

; A = environment (0 urban, 1 forest): HL = its pick_cache entry
; (difficulty, total), DE = its chunk_weights
env_cache:
                ld hl,pick_cache
                ld de,chunk_weights
                or a
                ret z
                ld hl,pick_cache+2
                ld de,chunk_weights+CHUNK_COUNT
                ret

; A = environment: its weights for the current difficulty
weigh_env:
                ld (.env),a
                call env_cache
                ld a,(difficulty)
                ld (hl),a
                push hl
                ld hl,chunk_table
                ld b,CHUNK_COUNT
                ld c,0                      ; C = total weight
.weigh:         push hl
                ld a,(hl)                   ; HL = chunk: rows, difficulty,
                inc hl                      ; weight, environment
                ld h,(hl)
                ld l,a
                inc hl
                ld a,(difficulty)
                cp (hl)
                jr c,.no                    ; too early for it
                inc hl
                inc hl
                ld a,(hl)                   ; environment: 0 any, 1 urban, 2 forest
                and CHUNK_ENV
                dec hl
                or a
                jr z,.yes
                dec a
                push bc
                ld b,a
                ld a,(.env)
                cp b
                pop bc
                jr nz,.no
.yes:           ld a,(hl)                   ; its weight
                jr .store
.no:            xor a
.store:         ld (de),a
                inc de
                add a,c
                ld c,a
                pop hl
                inc hl
                inc hl
                djnz .weigh
                ld a,c
                or a
                jr nz,.total
                inc c                       ; nothing eligible: the first one
.total:         pop hl
                inc hl
                ld (hl),c
                ret
.env:           defb 0

; a light frame (no coarse step): the weights of one environment brought up
; to the difficulty, if behind
chunk_prewarm:
                xor a
                call env_cache
                ld a,(difficulty)
                cp (hl)
                ld a,0
                jr nz,weigh_env
                inc a
                call env_cache
                ld a,(difficulty)
                cp (hl)
                ld a,1
                jr nz,weigh_env
                ret

; chunk lane k goes to lane chunk_lanes[k]; the first two keep neighbours
lane_orders:    defb 0,1,2, 2,1,0, 1,0,2, 0,2,1, 1,2,0, 2,0,1


; --- next row of the current chunk: the 3 cells in the chunk's lane order ---------
; IX = descriptor. Destroys AF, BC, DE, HL, IY.
chunk_row:
                ld hl,(chunk_ptr)
                ld a,(chunk_lanes)
                call .cell
                ld a,(chunk_lanes+1)
                call .cell
                ld a,(chunk_lanes+2)
                call .cell
                call place_powerup
                ld (chunk_ptr),hl
                ld hl,chunk_left
                dec (hl)
                ret
; A = lane the cell at HL goes to; HL += 1
.cell:          ld (row_lane),a
                ld e,a
                ld d,0
                push ix
                pop iy
                add iy,de
                ld a,(skill)                ; easy: at most 2 obstacles a lane
                or a                        ; on a screen
                call z,easy_cell
                ret c
                ld a,(hl)                   ; tile (+ #80: a coin)
                and #7F
                ld c,a
                ld a,(livery)               ; in the chunk's livery
                add a,c
                ld e,a
                ld d,livery_tiles>>8
                ld a,(de)
                ld (iy+D_LANES),a
                ld a,c                      ; its collision class
                add TILE_COLL_OFS
                ld e,a
                ld a,(de)
                ld (iy+D_COLL),a
                ld a,(hl)                   ; item
                inc hl
                rlca
                and 1
                ld (iy+D_ITEM),a
                ret z
                push hl
                call spawn_item
                pop hl
                ret

; -----------------------------------------------------------------------------
; Easy: a buffer stop or a signal that would be the third obstacle of its lane
; within EASY_WINDOW rows (a screen) becomes rail, both its rows. Trains stay
; (ramps, roofs), but count. HL = cell, IY = its descriptor cell, (row_lane) =
; lane. C: rail written (HL += 1), NC: an ordinary cell (HL kept).
; -----------------------------------------------------------------------------
EASY_WINDOW     equ CPC_PICTURE_ROWS

easy_cell:
                push hl
                call cell_coll              ; collision class
                and 15
                ld c,a
                ld a,(row_lane)
                ld hl,ez_obj
                call add_a_hl               ; bit 0: an obstacle on the row
                ld a,c                      ; below, bit 1: it is being dropped
                or a
                jr z,.clear
                cp COL_RAMP_UP
                jr c,.obstacle              ; stop, signal, train, cab
                cp COL_GAP
                jr z,.obstacle              ; coupler
.clear:         ld (hl),0
.keep:          pop hl
                or a
                ret
.obstacle:      bit 0,(hl)                  ; the same one as the row below
                jr z,.start
                bit 1,(hl)
                jr nz,.drop
                jr .keep
.start:         ld (hl),1
                ld a,(row_lane)             ; HL = its starts: newer, older
                add a,a
                add a,a
                ld hl,ez_starts
                call add_a_hl
                ld a,c
                cp COL_TRAIN
                jr nc,.record               ; a train stays
                push hl
                inc hl
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld hl,(gen_row)
                or a
                sbc hl,de                   ; rows since the older one
                ld de,EASY_WINDOW
                or a
                sbc hl,de
                pop hl
                jr c,.too_many
.record:        ld e,(hl)                   ; older = newer, newer = this row
                inc hl
                ld d,(hl)
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                ld de,(gen_row)
                dec hl
                dec hl
                ld (hl),d
                dec hl
                ld (hl),e
                jr .keep
.too_many:      ld a,(row_lane)
                ld hl,ez_obj
                call add_a_hl
                ld (hl),3
.drop:          pop hl
                ld (iy+D_LANES),TILE_RAIL_A
                ld (iy+D_COLL),COL_NONE
                ld (iy+D_ITEM),0
                inc hl
                scf
                ret

; HL = chunk cell: A = its collision class (from its tile). Keeps BC, DE, HL.
cell_coll:
                push de
                ld a,(hl)
                and #7F
                add TILE_COLL_OFS
                ld e,a
                ld d,livery_tiles>>8
                ld a,(de)
                pop de
                ret

; a new game: no obstacles below, the starts long ago
easy_reset:
                ld a,#FF                    ; (and the weights of the last
                ld (pick_cache),a           ; game: none yet)
                ld (pick_cache+2),a
                ld hl,ez_obj
                ld b,3
.obj:           ld (hl),0
                inc hl
                djnz .obj
                ld hl,(gen_row)
                ld de,-1000
                add hl,de
                ex de,hl
                ld hl,ez_starts
                ld b,6
.start:         ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                djnz .start
                ret

ez_obj:         defs 3                  ; per lane: bit 0 obstacle below, bit 1 dropped
ez_starts:      defs 3*4                ; per lane: rows of the last two obstacles

; -----------------------------------------------------------------------------
; place_powerup : when pu_gap is 0, a power-up on a free lane of this row
; (IX = descriptor, HL = the chunk's next row): plain rail and no
; item here and on the next row (it covers 2 rows), no obstacle in the
; PU_CLEAR rows ahead of it nor in the PU_CLEAR rows behind it (rail or
; ramps). Or on a wagon roof (not a coupler) in a chunk with a ramp, with the
; train going on PU_CLEAR rows ahead and behind (src/world.asm obstacle). Turbo PU_TURBO_ODDS/256,
; the other five share the rest. Then 50-150 rows to the next one.
; Preserves HL.
; -----------------------------------------------------------------------------
place_powerup:
                ld de,(pu_gap)
                ld a,d
                or e
                ret nz
                ld a,(chunk_left)           ; rows ahead in this chunk, then the
                dec a                       ; empty ones after it: PU_CLEAR
                ret z
                ld c,a
                ld a,(spacer_len)
                add a,c
                cp PU_CLEAR
                ret c
                ld a,c                      ; the chunk rows to check
                cp PU_CLEAR
                jr c,.rows
                ld a,PU_CLEAR
.rows:          ld (.check),a
                push hl
                ld c,3
                call random_below
                ld b,3                      ; B = lanes to try from lane A
.try:           ld (row_lane),a
                ld e,a
                ld d,0
                push ix
                pop iy
                add iy,de                   ; this row
                ld a,(iy+D_ITEM)
                or a
                jr nz,.next
                ld a,(iy+D_COLL)            ; on the ground (rail) or, in a chunk
                and 15                      ; with a ramp, on a wagon roof
                jr z,.surface
                cp COL_TRAIN
                jr nz,.next
                ld a,(roofs_reachable)
                or a
                jr z,.next
.surface:       ld (pu_roof),a
                ld a,e                      ; the rows behind
                call clear_behind
                jr nz,.next
                ld hl,chunk_src             ; the lane in the chunk's data
                add hl,de
                ld e,(hl)
                pop hl
                push hl
                add hl,de                   ; next row: its cell in that lane
                ld a,(hl)                   ; no item next to it (2 rows)
                rlca
                jr c,.next
                ld a,(pu_roof)              ; on a roof: not over a coupler
                or a
                jr z,.rows_ahead
                call cell_coll
                and 15
                cp COL_TRAIN
                jr nz,.next
.rows_ahead:    ld a,(.check)               ; and no obstacle in the rows ahead
                ld c,a
.ahead:         call cell_coll
                call obstacle
                jr nz,.next
                ld a,3                      ; the row above in the chunk
                call add_a_hl
                dec c
                jr nz,.ahead
                jr .found
.next:          ld a,(row_lane)
                inc a
                cp 3
                jr c,.lane_ok
                xor a
.lane_ok:       djnz .try
                pop hl
                ret                         ; none free: try the next row
.found:         call put_powerup
                pop hl
                ret
.check:         defb 0


chunk_weights:  defs 2*CHUNK_COUNT              ; urban, forest
pick_cache:     defb #FF,0,#FF,0                ; per env: their difficulty, total
chunk_lanes:    defb 0,1,2
chunk_src:      defb 0,1,2
livery:         defb 0                  ; offset of its table in livery_tiles
roofs_reachable: defb 0                 ; the chunk has a ramp up: roofs reachable

