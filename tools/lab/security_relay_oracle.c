// SPDX-License-Identifier: GPL-3.0-only
// Test oracle only: public libws73 API, not a second production Host.
#include "libws73-usb.h"
#include "sle73/sle73.h"
#include "sle73/sle73_priv.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static sle73_addr_t peer;
static int requested, done, failed, connecting, linked, cap_requested;
static uint16_t connection_handle;
#ifdef WS73_RELAY_DIAGNOSTIC_CONTROL
/* Observation only: real frame bytes; do not manufacture a protocol reply. */
void relay_control_receive(unsigned conn, unsigned idx,
                           const unsigned char *pdu, unsigned n) {
  if (conn != connection_handle || idx != 0x133 || n != 1 || pdu[0] != 2) {
    failed = 1;
    printf("RELAY_CONTROL_RX_MISMATCH\n");
    return;
  }
  printf("RELAY_CONTROL_RX_MATCH handle=%u index=0133 bytes=02\n", conn);
}
#endif

static void paired(uint16_t h, const sle73_addr_t *a, sle73_errcode_t status) {
  if (h != connection_handle || memcmp(a->addr, peer.addr, 6) || !requested ||
      done) {
    failed = 1;
    return;
  }
  printf("PAIR_RESULT handle=%u status=%u\n", h, (unsigned)status);
  done = 1;
  failed = status != SLE73_ERR_PAIR_REJECT;
}
static void connected(uint16_t h, const sle73_addr_t *a,
                      sle73_acb_state_t state, sle73_pair_state_t pair,
                      sle73_disc_reason_t reason) {
  printf("LINK handle=%u state=%u pair=%u reason=%u\n", h, state, pair, reason);
  if (state != SLE73_ACB_STATE_CONNECTED)
    return;
  if (memcmp(a->addr, peer.addr, 6) || requested) {
    failed = 1;
    return;
  }
  connection_handle = h;
  linked = 1;
  printf("RELAY_ORACLE_LINKED\n");
}
static void found(sle73_seek_result_t *r) {
  if (connecting || requested || memcmp(r->addr.addr, peer.addr, 6))
    return;
  connecting = 1;
  printf("FOUND rssi=%d\n", r->rssi);
  if (sle73_stop_seek() != SLE73_ERR_SUCCESS ||
      sle73_connect_remote_device(&r->addr) != SLE73_ERR_SUCCESS)
    failed = 1;
}
int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "--reset-only")) {
    /* Dedicated scratch guest's sole attached owner, not an arbitrary dongle. */
    if (access("/scratch-root-uuid", F_OK) != 0)
      return 32;
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (ws73_usb_init() < 0 || ws73_usb_open_path("1-1") < 0)
      return 30;
    int rc = ws73_usb_reset_device();
    printf("CONTROLLED_RESET_RESULT rc=%d\n", rc);
    ws73_usb_close();
    return rc < 0 ? 31 : 0;
  }
  unsigned a[6], b[6];
  struct ws73_usb_sle *ch = NULL;
  if (argc != 3 ||
      sscanf(argv[1], "%x:%x:%x:%x:%x:%x", &a[0], &a[1], &a[2], &a[3], &a[4],
             &a[5]) != 6 ||
      sscanf(argv[2], "%x:%x:%x:%x:%x:%x", &b[0], &b[1], &b[2], &b[3], &b[4],
             &b[5]) != 6)
    return 2;
  for (int i = 0; i < 6; i++) {
    if (a[i] > 255)
      return 2;
    peer.addr[i] = a[i];
  }
  peer.type = SLE73_ADDRESS_TYPE_PUBLIC;
  setvbuf(stdout, NULL, _IOLBF, 0);
  ws73_usb_set_log_level(4);
  if (ws73_usb_init() < 0 || ws73_usb_open() < 0)
    return 3;
  /* Explicit test handoff: native VM has already loaded SDK111. */
  if (ws73_usb_mode() != 5 || ws73_usb_sle_open(&ch) != WS73_OK)
    return 5;
  if (sle73_transport_attach(ws73_sle_fd(ch)) != SLE73_ERR_SUCCESS ||
      sle73_enable_sle() != SLE73_ERR_SUCCESS)
    return 6;
  sle73_addr_t local = {.type = SLE73_ADDRESS_TYPE_PUBLIC};
  for (int i = 0; i < 6; i++) {
    if (b[i] > 255)
      return 2;
    local.addr[i] = b[i];
  }
  if (sle73_set_local_addr(&local) != SLE73_ERR_SUCCESS)
    return 9;
  sle73_connection_callbacks_t c = {.connect_state_changed_cb = connected,
                                    .pair_complete_cb = paired};
  sle73_announce_seek_callbacks_t d = {.seek_result_cb = found};
  sle73_seek_param_t sp = {.seek_phys = SLE73_SEEK_PHY_1M,
                           .seek_type = {SLE73_SEEK_ACTIVE},
                           .seek_interval = {160},
                           .seek_window = {40}};
  if (sle73_connection_register_callbacks(&c) != SLE73_ERR_SUCCESS ||
      sle73_announce_seek_register_callbacks(&d) != SLE73_ERR_SUCCESS ||
      sle73_set_seek_param(&sp) != SLE73_ERR_SUCCESS ||
      sle73_start_seek() != SLE73_ERR_SUCCESS)
    return 7;
  struct timespec start, now;
  clock_gettime(CLOCK_MONOTONIC, &start);
  do {
    sle73_service_wait(100);
    if (linked && !cap_requested) {
      static const unsigned char cm[8] = {1, 7, 4, 0, 0xe2, 0, 0, 0};
      cap_requested = 1;
      if (sle73_core_send_acb(SLE73_TCID_CMTC, cm, sizeof(cm)) != WS73_OK)
        failed = 1;
      printf("CMTC_REQUEST_ENQUEUED id=7\n");
    }
    if (linked && !requested && access("/evidence/pair-allow", F_OK) == 0) {
      requested = 1;
      sle73_errcode_t rc = sle73_pair_remote_device(&peer);
      printf("PAIR_REQUEST handle=%u result=%u\n", connection_handle,
             (unsigned)rc);
      if (rc != SLE73_ERR_SUCCESS)
        failed = 1;
    }
    clock_gettime(CLOCK_MONOTONIC, &now);
  } while (!done && !failed && now.tv_sec - start.tv_sec < 30);
  printf("RELAY_ORACLE_%s requested=%d done=%d\n",
         done && !failed ? "PASS" : "FAIL", requested, done);
  sle73_disconnect_all_remote_device();
  sle73_disable_sle();
  ws73_usb_sle_close(ch);
  ws73_usb_close();
  return done && !failed ? 0 : 8;
}
