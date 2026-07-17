/*
 * espctl - control real ESP32-S3 hardware (GPIO, I2C) from native Linux.
 *
 * Uses the Linux GPIO character-device uAPI (GPIO v2, /dev/gpiochip0) and
 * the standard i2c-dev interface (/dev/i2c-0) directly -- no extra
 * userspace library dependency (libgpiod etc.), just kernel headers.
 *
 * SPDX-License-Identifier: MIT
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/utsname.h>
#include <sys/sysinfo.h>
#include <linux/gpio.h>
#include <linux/i2c-dev.h>

#define GPIOCHIP_PATH "/dev/gpiochip0"

/*
 * Allow-list of GPIO numbers safe to expose to userspace on the
 * esp32s3-devkit-c1 profile. Excludes: 0/3/45/46 (strapping pins -- can
 * force download mode or brownout detect on next reset), 6/7 (I2C0, already
 * owned by the i2c-gpio kernel driver), 10-13 (SPI2/microSD), 19/20 (USB
 * D-/D+), 26-32 (Octal PSRAM/flash -- touching these can hang or corrupt
 * the running system), 43/44 (UART0, the serial console).
 */
static const int allowed_pins[] = {
	1, 2, 4, 5, 8, 14, 15, 16, 17, 18, 21, 38, 39, 40, 41, 42, 47, 48
};

static int pin_allowed(int pin)
{
	size_t i;
	for (i = 0; i < sizeof(allowed_pins) / sizeof(allowed_pins[0]); i++)
		if (allowed_pins[i] == pin)
			return 1;
	return 0;
}

static void print_allowed_pins(void)
{
	size_t i;
	fprintf(stderr, "allowed pins:");
	for (i = 0; i < sizeof(allowed_pins) / sizeof(allowed_pins[0]); i++)
		fprintf(stderr, " %d", allowed_pins[i]);
	fprintf(stderr, "\n");
}

static int gpio_request_line(int pin, __u64 direction_flag, int initial_value)
{
	struct gpio_v2_line_request req;
	int chip_fd, ret;

	chip_fd = open(GPIOCHIP_PATH, O_RDWR);
	if (chip_fd < 0) {
		perror("open " GPIOCHIP_PATH);
		return -1;
	}

	memset(&req, 0, sizeof(req));
	req.num_lines = 1;
	req.offsets[0] = (__u32) pin;
	strncpy(req.consumer, "espctl", sizeof(req.consumer) - 1);
	req.config.flags = direction_flag;

	if (direction_flag & GPIO_V2_LINE_FLAG_OUTPUT) {
		req.config.num_attrs = 1;
		req.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
		req.config.attrs[0].attr.values = initial_value ? 1 : 0;
		req.config.attrs[0].mask = 1;
	}

	ret = ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, &req);
	close(chip_fd);
	if (ret < 0) {
		perror("GPIO_V2_GET_LINE_IOCTL");
		return -1;
	}

	return req.fd;
}

static int cmd_gpio_set(int pin, int value)
{
	int line_fd;
	struct gpio_v2_line_values vals;

	if (!pin_allowed(pin)) {
		fprintf(stderr, "espctl: gpio %d is not in the allow-list\n", pin);
		print_allowed_pins();
		return 1;
	}

	line_fd = gpio_request_line(pin, GPIO_V2_LINE_FLAG_OUTPUT, value);
	if (line_fd < 0)
		return 1;

	memset(&vals, 0, sizeof(vals));
	vals.mask = 1;
	vals.bits = value ? 1 : 0;
	if (ioctl(line_fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &vals) < 0) {
		perror("GPIO_V2_LINE_SET_VALUES_IOCTL");
		close(line_fd);
		return 1;
	}

	printf("gpio %d = %d\n", pin, value ? 1 : 0);
	close(line_fd);
	return 0;
}

static int cmd_gpio_get(int pin)
{
	int line_fd;
	struct gpio_v2_line_values vals;

	if (!pin_allowed(pin)) {
		fprintf(stderr, "espctl: gpio %d is not in the allow-list\n", pin);
		print_allowed_pins();
		return 1;
	}

	line_fd = gpio_request_line(pin, GPIO_V2_LINE_FLAG_INPUT, 0);
	if (line_fd < 0)
		return 1;

	memset(&vals, 0, sizeof(vals));
	vals.mask = 1;
	if (ioctl(line_fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &vals) < 0) {
		perror("GPIO_V2_LINE_GET_VALUES_IOCTL");
		close(line_fd);
		return 1;
	}

	printf("gpio %d = %d\n", pin, (int) (vals.bits & 1));
	close(line_fd);
	return 0;
}

static int cmd_i2c_scan(const char *bus_path)
{
	int fd, addr;

	fd = open(bus_path, O_RDWR);
	if (fd < 0) {
		perror(bus_path);
		return 1;
	}

	printf("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\n");
	for (addr = 0; addr < 0x80; addr++) {
		if (addr % 16 == 0)
			printf("%02x: ", addr);

		/* Reserved/general-call ranges: skip probing, print blank. */
		if (addr < 0x03 || addr > 0x77) {
			printf("   ");
		} else if (ioctl(fd, I2C_SLAVE, addr) < 0) {
			printf("   ");
		} else {
			/* A 0-byte read is enough to detect NAK/ACK on most devices. */
			unsigned char dummy;
			if (read(fd, &dummy, 0) >= 0 || errno != 6 /* ENXIO */)
				printf("%02x ", addr);
			else
				printf("-- ");
		}

		if (addr % 16 == 15)
			printf("\n");
	}

	close(fd);
	return 0;
}

static int cmd_system_info(void)
{
	struct utsname uts;
	struct sysinfo si;

	if (uname(&uts) == 0) {
		printf("kernel:    %s %s\n", uts.sysname, uts.release);
		printf("machine:   %s\n", uts.machine);
	}

	if (sysinfo(&si) == 0) {
		printf("uptime:    %ld s\n", si.uptime);
		printf("mem total: %lu KB\n", si.totalram * si.mem_unit / 1024);
		printf("mem free:  %lu KB\n", si.freeram * si.mem_unit / 1024);
	}

	printf("gpiochip:  %s\n", GPIOCHIP_PATH);
	return 0;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s gpio set <pin> <0|1>\n"
		"       %s gpio get <pin>\n"
		"       %s i2c scan [/dev/i2c-N]\n"
		"       %s system info\n",
		argv0, argv0, argv0, argv0);
}

int main(int argc, char **argv)
{
	if (argc < 3) {
		usage(argv[0]);
		return 1;
	}

	if (!strcmp(argv[1], "gpio")) {
		if (!strcmp(argv[2], "set") && argc == 5)
			return cmd_gpio_set(atoi(argv[3]), atoi(argv[4]));
		if (!strcmp(argv[2], "get") && argc == 4)
			return cmd_gpio_get(atoi(argv[3]));
	} else if (!strcmp(argv[1], "i2c")) {
		if (!strcmp(argv[2], "scan"))
			return cmd_i2c_scan(argc > 3 ? argv[3] : "/dev/i2c-0");
	} else if (!strcmp(argv[1], "system")) {
		if (!strcmp(argv[2], "info"))
			return cmd_system_info();
	}

	usage(argv[0]);
	return 1;
}
