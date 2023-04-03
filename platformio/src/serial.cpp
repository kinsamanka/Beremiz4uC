/*
 * This file is part of Beremiz for uC
 *
 * Copyright (C) 2023 GP Orcullo
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program; If not, see <http://www.gnu.org/licenses/>.
 *
 */

#include <Arduino.h>
#include <string.h>
#include <stdbool.h>

#include "async.h"
#include "async-sem.h"
#include "hw.h"
#include "serial.h"

extern "C" {
#include "min.h"
#include "debug.h"

void config_init__(void);
}

#define MIN_KEEP_ALIVE          0
#define MIN_PLC_START           1
#define MIN_PLC_STOP            2
#define MIN_PLC_RESET           3
#define MIN_PLC_INIT            4
#define MIN_PLC_UPLOAD          5
#define MIN_PLC_FORCE           6
#define MIN_PLC_TICK            7
#define MIN_PLC_SET_TRACE       8
#define MIN_PLC_GET_TRACE       9
#define MIN_PLC_WAIT_TRACE      10
#define MIN_PLC_RESET_TRACE     11

#define BUFFER_SIZE             32

#if ARDUINO_ARCH_STM32 && defined STM32F1xx
#include <stm32f1xx_hal_cortex.h>
static inline void run_bootloader(void)
{
    *((volatile uint32_t *)(0x20001800)) = 0xDEADBEEF;  /* set flag */
    HAL_NVIC_SystemReset();
}

static inline void reset(void)
{
    HAL_NVIC_SystemReset();
}
#else
static void run_bootloader(void)
{
}

static inline void reset(void)
{
}
#endif

extern unsigned long tick;

void plc_run(bool);

static struct async_sem ready;

static struct min_context min_ctx;

static struct min_poll_state {
    async_state;
    uint8_t buf;
    uint8_t len;
    unsigned long keepalive;
    unsigned long dt;
} min_poll_state;

static struct min_state {
    async_state;
    unsigned long dt;
    unsigned long last_tick;
    size_t idx;
} min_state;

static struct {
    uint8_t buf[BUFFER_SIZE];
    uint8_t id;
    uint8_t len;
} min_data;

static async min_task(unsigned long dt, struct min_state *pt)
{
    size_t idx;

    async_begin(pt);

    pt->dt = dt;
    pt->last_tick = tick - 1;       /* ensure tick is always sent first */

    while (1) {
        await_sem(&ready);

        if (min_data.id == MIN_KEEP_ALIVE) {

            min_queue_frame(&min_ctx, MIN_KEEP_ALIVE, 0, 0);

        } else if (min_data.id == MIN_PLC_START) {

            plc_run(true);
            min_queue_frame(&min_ctx, MIN_PLC_START, 0, 0);

        } else if (min_data.id == MIN_PLC_STOP) {

            plc_run(false);
            min_queue_frame(&min_ctx, MIN_PLC_STOP, 0, 0);

        } else if (min_data.id == MIN_PLC_RESET) {

            reset();

        } else if (min_data.id == MIN_PLC_INIT) {

            config_init__();
            tick = 0;

        } else if (min_data.id == MIN_PLC_UPLOAD) {

            run_bootloader();

        } else if (min_data.id == MIN_PLC_FORCE) {

            force_var(0, 0, 0);

        } else if (min_data.id == MIN_PLC_WAIT_TRACE) {

            pt->last_tick = tick;

            await (tick != pt->last_tick);

            pt->last_tick = tick;
            min_queue_frame(&min_ctx, MIN_PLC_TICK, (uint8_t *) & tick, 4);

            idx = ((uint16_t *)min_data.buf)[0];

            min_queue_frame(&min_ctx, MIN_PLC_GET_TRACE,
                            (uint8_t *)get_var_addr(idx),
                            get_var_size(idx));
            async_yield;

        } else if (min_data.id == MIN_PLC_GET_TRACE) {

            if (tick != pt->last_tick) {

                pt->last_tick = tick;
                min_queue_frame(&min_ctx, MIN_PLC_TICK, (uint8_t *) & tick, 4);

            }

            idx = ((uint16_t *)min_data.buf)[0];

            min_queue_frame(&min_ctx, MIN_PLC_GET_TRACE,
                            (uint8_t *)get_var_addr(idx),
                            get_var_size(idx));
            async_yield;

        } else if (min_data.id == MIN_PLC_SET_TRACE) {

            idx = ((size_t *)min_data.buf)[0];
            if (((size_t *)min_data.buf)[1] == get_var_size(idx))
                set_trace(idx, ((bool *)min_data.buf)[8],
                          (void *)&min_data.buf[9]);

        } else if (min_data.id == MIN_PLC_RESET_TRACE) {

            trace_reset();

        } else {

            min_queue_frame(&min_ctx, MIN_KEEP_ALIVE, 0, 0);
        }
    }

    async_end;
}

static async min_poll_task(unsigned long dt, struct min_poll_state *pt)
{
    async_begin(pt);

    pt->keepalive = 0 - MIN_TIMEOUT;

    while (1) {
        min_poll(&min_ctx, &pt->buf, pt->len);

        if (MINPORT.available()) {
            pt->buf = MINPORT.read();
            pt->len = 1;
        } else {
            pt->len = 0;
        }

        /* keep alive */
        if (dt - pt->keepalive > MIN_TIMEOUT) {
            pt->keepalive = dt;
            min_transport_reset(&min_ctx, 1);
            min_queue_frame(&min_ctx, MIN_KEEP_ALIVE, 0, 0);
        }

        pt->dt = dt;

        async_yield;
    }

    async_end;
}

void min_application_handler(uint8_t min_id,
                             uint8_t const *min_payload, uint8_t len_payload,
                             uint8_t port)
{
    /* keep alive */
    min_poll_state.keepalive = min_poll_state.dt;

    min_data.id = min_id;
    min_data.len = len_payload;
    memcpy(min_data.buf, min_payload, len_payload);

    signal_sem(&ready);
}

uint16_t min_tx_space(uint8_t port)
{
    return MINPORT.availableForWrite();
}

void min_tx_byte(uint8_t port, uint8_t byte)
{
    MINPORT.write(byte);
}

uint32_t min_time_ms(void)
{
    return millis();
}

void serial_init(void)
{
    Serial2.begin(STM32_BAUD_RATE);
    Serial2.flush();

    MINPORT.begin(STM32_BAUD_RATE);
    MINPORT.flush();

    init_sem(&ready, 0);

    async_init(&min_poll_state);
    async_init(&min_state);

    min_init_context(&min_ctx, 0);
}

void serial_task(unsigned long dt, int run)
{
    min_poll_task(dt, &min_poll_state);
    min_task(dt, &min_state);
}
