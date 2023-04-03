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

#include "iec_std_lib.h"

void update_time(void);

IEC_TIME __CURRENT_TIME;
IEC_BOOL __DEBUG;
extern unsigned long long common_ticktime__;

void update_time(void)
{
    const TIME ticktime = {0, common_ticktime__};

    __CURRENT_TIME = __time_add(__CURRENT_TIME, ticktime);
}
