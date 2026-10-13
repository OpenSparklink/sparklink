#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual C registration rejection paths with dependency fixtures, no devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(kernel, compiler):
    kernel = Path(kernel).resolve(strict=True)
    source = (kernel / 'net/sparklink/sle_native_ffi.c').read_text()
    start = source.index('static int sparklink_backend_register_identity(')
    body = source[start:source.index('EXPORT_SYMBOL_GPL(sparklink_backend_register);', start)]
    start = source.index('struct sparklink_native_transport {')
    transport = source[start:source.index('};', start) + 2]
    start = source.index('u32 sparklink_native_transport_bus(')
    getter = source[start:source.index('\nvoid sparklink_native_transport_get', start)]
    start = source.index('int sparklink_backend_register_reserved(')
    reserved_body = source[start:source.index('EXPORT_SYMBOL_GPL(sparklink_backend_register_reserved);',start)]
    fixture = r'''
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <linux/sparklink_backend.h>
typedef unsigned int refcount_t;
static unsigned int allocations, modules, contexts, rust_calls;
static struct sparklink_native_transport *accepted;
static struct sparklink_native_identity copied_reservation;
#define kmalloc_obj(object) dependency_alloc(sizeof(object))
#define kfree free
static void *dependency_alloc(size_t n) { ++allocations; return malloc(n); }
static int try_module_get(struct module *m) { (void)m; ++modules; return 1; }
static void refcount_set(refcount_t *r, unsigned int n) { *r=n; }
'''
    fixture += transport
    fixture += r'''
static int sparklink_native_register_rust(const struct sparklink_native_info *i,
 struct sparklink_native_transport *t, const struct sparklink_native_identity *reserved, struct sparklink_native_identity *out)
{ (void)i; (void)out; if(reserved) copied_reservation=*reserved; ++rust_calls; accepted=t; return 0; }
static void retain(void *c) { (void)c; ++contexts; }
static int open_backend(void *c, u16 i, u64 g) { (void)c; (void)i; (void)g; return 0; }
static int command(void *c, u16 o, const u8 *p, size_t n)
{ (void)c; (void)o; (void)p; (void)n; return 0; }
'''
    fixture += getter
    fixture += body
    fixture += reserved_body
    fixture += r'''
int main(void) {
 struct sparklink_native_ops ops = { .get=retain,.put=retain,.open=open_backend,
  .close=retain,.validate_command=command,.send_command=command };
 struct sparklink_backend_descriptor valid = { .version=1,.size=sizeof(valid),
  .bus=1,.info={.profile=1},.ops=&ops,.context=&ops }, d;
 struct sparklink_native_identity out={.id=123,.generation=456};
 unsigned int tests=0;
#define CHECK(desc, output, expected) do { int r=sparklink_backend_register(desc,output); ++tests; \
 if(r!=(expected)||allocations||modules||contexts||rust_calls||out.id!=123||out.generation!=456) { \
 fprintf(stderr,"registration reject %u returned %d, side effects %u/%u/%u/%u\n",tests,r,allocations,modules,contexts,rust_calls);return 1; } } while(0)
 CHECK(NULL,&out,-EINVAL); CHECK(&valid,NULL,-EINVAL);
 d=valid;d.version=0;d.ops=(void *)1;CHECK(&d,&out,-EOPNOTSUPP);
 d=valid;d.size=sizeof(d)-1;d.ops=(void *)1;CHECK(&d,&out,-EOPNOTSUPP);
 d=valid;d.bus=0;d.ops=(void *)1;CHECK(&d,&out,-EOPNOTSUPP);
 d=valid;d.info.profile=0;d.ops=(void *)1;CHECK(&d,&out,-EOPNOTSUPP);
 d=valid;d.capabilities=8;d.ops=(void *)1;CHECK(&d,&out,-EOPNOTSUPP);
 d=valid;d.ops=NULL;CHECK(&d,&out,-EINVAL);
 d=valid;d.context=NULL;CHECK(&d,&out,-EINVAL);
 d=valid;d.capabilities=SPARKLINK_BACKEND_ACB;CHECK(&d,&out,-EINVAL);
 ops.get=NULL;CHECK(&valid,&out,-EINVAL);
 ops.get=retain;
 {
  struct sparklink_native_identity bad={.id=0,.generation=0};
  if(sparklink_backend_register_reserved(&valid,NULL,&out)!=-EINVAL) return 4;
  if(sparklink_backend_register_reserved(&valid,&bad,&out)!=-EINVAL) return 5;
  bad.id=16;bad.generation=1;
  if(sparklink_backend_register_reserved(&valid,&bad,&out)!=-EINVAL) return 6;
  if(allocations||modules||contexts||rust_calls) return 7;
 }
 for (unsigned int bus=SPARKLINK_BACKEND_USB;bus<=SPARKLINK_BACKEND_TEST;++bus) {
  d=valid;d.bus=bus;allocations=modules=contexts=rust_calls=0;accepted=NULL;
  if(sparklink_backend_register(&d,&out)!=0 || !accepted ||
     allocations!=1 || modules!=1 || contexts!=1 || rust_calls!=1 ||
     sparklink_native_transport_bus(accepted)!=bus) return 2;
  /* Source descriptor is gone/mutable after registration; provenance is copied. */
  d.bus=99;
  if(sparklink_native_transport_bus(accepted)!=bus) return 3;
  free(accepted); accepted=NULL;
 }
 {
  struct sparklink_native_identity id={.id=3,.generation=7};
  allocations=modules=contexts=rust_calls=0;
  if(sparklink_backend_register_reserved(&valid,&id,&out)!=0 || copied_reservation.id!=3 || copied_reservation.generation!=7) return 8;
  free(accepted);accepted=NULL;
 }
 printf("ACTUAL_BACKEND_REGISTRATION_REJECT_PASS tests=%u bus_copy_cases=2\n",tests);
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='sparklink-backend-registration-') as temporary:
        directory = Path(temporary)
        c = directory / 'actual.c'
        executable = directory / 'actual'
        c.write_text(fixture)
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-I', str(kernel / 'include'), str(c), '-o', str(executable)], check=True)
        result = subprocess.check_output([str(executable)], text=True)
    print(json.dumps({'status': 'ACTUAL_BACKEND_REGISTRATION_REJECT_PASS', 'tests': 11, 'bus_copy_cases': 2, 'reserved_rejection_cases': 3, 'reserved_copy_cases': 1,
                      'reserved_body_sha256': hashlib.sha256(reserved_body.encode()).hexdigest(),
                      'bus_getter_sha256': hashlib.sha256(getter.encode()).hexdigest(),
                      'actual_function_sha256': hashlib.sha256(body.encode()).hexdigest(),
                      'production_file_sha256': hashlib.sha256(source.encode()).hexdigest(),
                      'result': result.strip(), 'hardware_acceptance': False,
                      'scope': 'actual C entry body; dependency allocation/module/Rust callback fixtures; invalid ops sentinel must not be followed for unsupported layout/bus/dialect/caps; positive USB/TEST provenance copied before dependency Rust registration and retained after descriptor mutation; no kernel reference or concurrent lifetime proof'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--cc', default=os.environ.get('CC', 'clang'))
    args = parser.parse_args()
    run(args.kernel, args.cc)
