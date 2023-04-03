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

#include "hw.h"
#include "tasks.h"

extern "C" void __task(unsigned long, int) {}

void serial_task(unsigned long, int) __attribute__((weak, alias("__task")));
void wifi_task(unsigned long, int)   __attribute__((weak, alias("__task")));
void eth_task(unsigned long, int)    __attribute__((weak, alias("__task")));

struct task_state {
    async_state;
} ts;

struct blink_task_state {
    async_state;
    unsigned long dt;
} bts;

static async blink_task(unsigned long dt, int run)
{
    if (RUN_LED) {
        async_begin(&bts);

        bts.dt = dt;

        while (1) {
            digitalWrite(RUN_LED, HIGH);
            await((dt - bts.dt) > 300);

            await(run);

            digitalWrite(RUN_LED, LOW);
            await((dt - bts.dt) > 900);

            bts.dt = dt;
        }

        async_end;

    } else {
        return ASYNC_DONE;
    }
}

async run_tasks(unsigned long dt, int run)
{
    async_begin(&ts);

    while (1) {

        blink_task(dt, run);

        serial_task(dt, run);
        async_yield;

        wifi_task(dt, run);
        async_yield;

        eth_task(dt, run);
        async_yield;
    }

    async_end;
}
