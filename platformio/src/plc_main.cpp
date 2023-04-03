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

unsigned long tick = 0;
unsigned long scan_cycle;
unsigned long timer_ms = 0;
extern unsigned long long common_ticktime__;

extern "C" {
    void update_time();
    void config_run__(unsigned long tick);
    void config_init__(void);
    void __empty(void) {}
}

void eth_init()       __attribute__((weak, alias("__empty")));
void hardware_init()  __attribute__((weak, alias("__empty")));
void modbus_init()    __attribute__((weak, alias("__empty")));
void serial_init()    __attribute__((weak, alias("__empty")));
void update_inputs()  __attribute__((weak, alias("__empty")));
void update_outputs() __attribute__((weak, alias("__empty")));
void wifi_init()      __attribute__((weak, alias("__empty")));

static enum {
    PLC_STOP,
    PLC_RUN,
    PLC_ERR,
} plc_state;

void setup()
{
    hardware_init();
#if DEBUG
    LL_GPIO_AF_Remap_SWJ_NOJTAG();
#endif

    if (RUN_LED)
        pinMode(RUN_LED, OUTPUT);

    if (ERR_LED)
        pinMode(ERR_LED, OUTPUT);

    if (RUN_SW)
        pinMode(RUN_SW, INPUT);

    scan_cycle = (uint32_t) (common_ticktime__ / 1000000);
    timer_ms = millis() + scan_cycle;

    serial_init();
    modbus_init();
    wifi_init();
    eth_init();

    config_init__();

    plc_state = PLC_STOP;
}

void loop()
{
    unsigned long dt = millis();

    int run = 0;

    if (plc_state == PLC_STOP)
        run = IS_RUN_SW;
    else
        run = (plc_state == PLC_RUN);

    if (dt >= timer_ms) {

        timer_ms += scan_cycle;

        if (run) {
            update_inputs();
            config_run__(tick++);
            update_outputs();
            update_time();
        }
    }

    run_tasks(dt, run);
}

void plc_run(bool state)
{
    if (state)
        plc_state = PLC_RUN;
    else
        plc_state = PLC_STOP;
}
