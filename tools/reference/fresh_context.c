// SPDX-License-Identifier: GPL-2.0-only
// VM-only reference diagnostic; never linked into the production driver or
// daemon.
#include <libusb.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
int main(void) {
  for (int j = 0; j < 140; j++) {
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    printf("%ld.%09ld init_rc=%d", t.tv_sec, t.tv_nsec, rc);
    if (!rc) {
      libusb_device **list;
      ssize_t n = libusb_get_device_list(ctx, &list);
      for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d = {0};
        libusb_get_device_descriptor(list[i], &d);
        if (d.idVendor != 0xffff || d.idProduct != 0x3733)
          continue;
        struct libusb_config_descriptor *c = NULL;
        int cr = libusb_get_active_config_descriptor(list[i], &c);
        printf(" dev=%u:%u bcd=%04x cfg_rc=%d eps=%d",
               libusb_get_bus_number(list[i]),
               libusb_get_device_address(list[i]), d.bcdDevice, cr,
               cr == 0 && c->bNumInterfaces && c->interface[0].num_altsetting
                   ? c->interface[0].altsetting[0].bNumEndpoints
                   : -1);
        if (c)
          libusb_free_config_descriptor(c);
      }
      if (n >= 0)
        libusb_free_device_list(list, 1);
      libusb_exit(ctx);
    }
    puts("");
    fflush(stdout);
    struct timespec s = {0, 100000000};
    nanosleep(&s, NULL);
  }
  return 0;
}
