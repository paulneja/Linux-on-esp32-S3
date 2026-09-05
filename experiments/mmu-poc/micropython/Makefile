MP_SOURCE ?= ../out/micropython-src
BUILD ?= ../out/micropython-build
include $(MP_SOURCE)/py/mkenv.mk
QSTR_DEFS = qstrdefsport.h
MICROPY_ROM_TEXT_COMPRESSION = 1
include $(TOP)/py/py.mk
INC = -I. -I../sdk -I$(TOP) -I$(BUILD)
CFLAGS += $(INC) -std=c99 -Os -g -DNDEBUG -Wall -Werror \
    -mno-fdpic -mabi=call0 -fno-pic -fno-pie -mauto-litpools \
    -ffreestanding -fno-stack-protector -ffunction-sections -fdata-sections
LDFLAGS = -nostdlib -static -Wl,-m,elf32xtensa,--build-id=none,--gc-sections \
    -Wl,-T,../payload.ld,-Map,$(BUILD)/micropython.map
SRC_C = main.c shared/libc/string0.c shared/libc/printf.c shared/runtime/stdout_helpers.c
SRC_QSTR += main.c
OBJ += $(PY_CORE_O) $(addprefix $(BUILD)/,$(SRC_C:.c=.o)) \
       $(BUILD)/setjmp.o $(BUILD)/bridge.o
all: $(BUILD)/micropython.elf
$(BUILD)/micropython.elf: $(OBJ) ../payload.ld
	$(Q)$(CC) $(LDFLAGS) -o $@ $(OBJ)
	$(SIZE) $@
include $(TOP)/py/mkrules.mk
