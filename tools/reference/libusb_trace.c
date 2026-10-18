// SPDX-License-Identifier: GPL-2.0-only
// VM-only reference diagnostic; never linked into the production driver or
// daemon.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <libusb.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
static void snapshot(const char *kind, libusb_context *ctx,
                     libusb_device **list, ssize_t n) {
  FILE *f = fopen("/evidence/reference-libusb-trace.tsv", "a");
  if (!f)
    return;
  struct timespec t;
  clock_gettime(CLOCK_REALTIME, &t);
  fprintf(f, "%ld.%09ld\t%d\t%s\t%p\t%zd", t.tv_sec, t.tv_nsec, getpid(), kind,
          (void *)ctx, n);
  int (*desc)(libusb_device *, struct libusb_device_descriptor *) =
      dlsym(RTLD_NEXT, "libusb_get_device_descriptor");
  int (*cfg)(libusb_device *, struct libusb_config_descriptor **) =
      dlsym(RTLD_NEXT, "libusb_get_active_config_descriptor");
  for (ssize_t i = 0; i < n; i++) {
    struct libusb_device_descriptor d = {0};
    int rc = desc(list[i], &d);
    if (rc || d.idVendor != 0xffff || d.idProduct != 0x3733)
      continue;
    struct libusb_config_descriptor *c = NULL;
    int cr = cfg(list[i], &c);
    unsigned char ports[8];
    int pn = libusb_get_port_numbers(list[i], ports, 8);
    fprintf(f, "\tdev=%u:%u,path=", libusb_get_bus_number(list[i]),
            libusb_get_device_address(list[i]));
    for (int j = 0; j < pn; j++)
      fprintf(f, "%s%u", j ? "." : "", ports[j]);
    fprintf(f, ",bcd=%04x,cfg_rc=%d,eps=%d", d.bcdDevice, cr,
            cr == 0 && c->bNumInterfaces && c->interface[0].num_altsetting
                ? c->interface[0].altsetting[0].bNumEndpoints
                : -1);
    if (c)
      libusb_free_config_descriptor(c);
  }
  fputc('\n', f);
  fclose(f);
}
ssize_t libusb_get_device_list(libusb_context *ctx, libusb_device ***list) {
  ssize_t (*real)(libusb_context *, libusb_device ***) =
      dlsym(RTLD_NEXT, "libusb_get_device_list");
  ssize_t n = real(ctx, list);
  snapshot("device_list", ctx, n >= 0 ? *list : NULL, n);
  return n;
}
int libusb_open(libusb_device *dev, libusb_device_handle **h) {
  int (*real)(libusb_device *, libusb_device_handle **) =
      dlsym(RTLD_NEXT, "libusb_open");
  int rc = real(dev, h);
  FILE *f = fopen("/evidence/reference-libusb-trace.tsv", "a");
  if (f) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    fprintf(f, "%ld.%09ld\t%d\topen\tdev=%u:%u\trc=%d\n", t.tv_sec, t.tv_nsec,
            getpid(), libusb_get_bus_number(dev),
            libusb_get_device_address(dev), rc);
    fclose(f);
  }
  return rc;
}
