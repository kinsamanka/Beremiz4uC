#ifndef hw_h
#define hw_h

#define DEBUG                       1

#ifndef RUN_LED
#define RUN_LED                     0
#endif

#ifndef ERR_LED
#define ERR_LED                     0
#endif

#ifndef RUN_SW
#define RUN_SW                      0
#define IS_RUN_SW                   1
#else
#define IS_RUN_SW                   digitalRead(RUN_SW)
#endif

#endif
