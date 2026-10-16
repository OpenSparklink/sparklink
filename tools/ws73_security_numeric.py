# SPDX-License-Identifier: GPL-2.0-only
"""VM-only original-author numeric mechanism witness; never a Host or Agent.

Both kernels compute their own fresh code. This disposable witness reads and
compares them, then decides the existing prompts; it supplies no proof/key/PDU.
Automated equality is NOT a human identity check or trusted application grant.
"""
import ctypes
import errno
import time
from sparklink.structs import SleSecurityNumericConfirm as Confirm
from sparklink.structs import SleSecurityNegotiationResult as Result
from ws73_security_capabilities import denied
from ws73_management_setup import decode

OFFER = bytes([1, 0, 4, 16, 0, 2, 2, 2, 2, 0])
CONFIRM = (1 << 30) | (ctypes.sizeof(Confirm) << 16) | (ord('S') << 8) | 0xd5
MODES = ('numeric-approve', 'numeric-reject', 'numeric-late')


def decision(req, code, accept=True):
    return Confirm(version=1, generation=req.generation, lifetime=req.lifetime,
                   request_id=req.request_id, handle=req.handle,
                   comparison_code=code, accept=int(accept))


def finish_exchange(r, row, save, writers, observers, requests, links):
    mode = r['numeric_comparison']
    if mode not in MODES:
        raise ValueError('explicit numeric mechanism mode required')
    numeric = row['numeric'] = dict(mode=mode, decisions=[], negatives=[])
    deadline = max(q.deadline_monotonic_ns for q in requests) + 1_000_000_000

    def read():
        return [a.security_negotiation(l.lifetime, l.handle, 1)
                for a, l in zip(writers, links)]

    while True:
        values = read()
        if all(v.state == 3 and v.flags & 8 for v in values):
            break
        if any(v.state in (5, 6, 7, 11) for v in values) or time.monotonic_ns() >= deadline:
            row['results'] = [bytes(v).hex() for v in values]; save()
            raise ValueError('both live actual numeric prompts required')
        time.sleep(.002)
    numeric['prompts'] = [bytes(v).hex() for v in values]
    numeric['prompt_wall_ns'] = time.time_ns()
    numeric['prompt_monotonic_ns'] = time.monotonic_ns()
    codes = [v.comparison_code for v in values]
    if codes[0] != codes[1] or not 0 <= codes[0] < 1_000_000:
        save(); raise ValueError('independently computed comparison codes differ')
    for n, req in enumerate(requests):
        for kind, want in [('code', errno.ESTALE), ('request', errno.ENOENT),
                           ('reserved', errno.EINVAL), ('accept', errno.EINVAL),
                           ('nonowner', errno.EPERM)]:
            q = decision(req, codes[n])
            if kind == 'code': q.comparison_code = (codes[n] + 1) % 1_000_000
            elif kind == 'request': q.request_id += 1
            elif kind == 'reserved': q.reserved[0] = 1
            elif kind == 'accept': q.accept = 2
            before = time.monotonic_ns()
            actual = denied((observers if kind == 'nonowner' else writers)[n].fileno(), CONFIRM, q)
            numeric['negatives'].append(dict(index=n, kind=kind, errno=actual,
                input=bytes(q).hex(), before_monotonic_ns=before, after_monotonic_ns=time.monotonic_ns()))
            save()
            if actual != want: raise ValueError('numeric decision negative: ' + kind)
    if mode != 'numeric-late':
        for n in ([r['index']] if mode == 'numeric-reject' else [r['index'], 1-r['index']]):
            q = decision(requests[n], codes[n], mode == 'numeric-approve')
            d = dict(index=n, input=bytes(q).hex(), before_wall_ns=time.time_ns(),
                     before_monotonic_ns=time.monotonic_ns())
            writers[n].confirm_security_numeric(q)
            d.update(after_wall_ns=time.time_ns(), after_monotonic_ns=time.monotonic_ns())
            numeric['decisions'].append(d); save()
    while True:
        values = read(); row['results'] = [bytes(v).hex() for v in values]; save()
        wanted = [11, 11] if mode == 'numeric-approve' else ([5 if n == r['index'] else 7 for n in (0, 1)] if mode == 'numeric-reject' else [7, 7])
        if [v.state for v in values] == wanted: break
        if time.monotonic_ns() >= deadline: raise TimeoutError('numeric mechanism original deadline/terminal states')
        if mode == 'numeric-approve' and any(v.state in (5, 6, 7) for v in values):
            raise ValueError('numeric confirmation/proof/installation failed')
        time.sleep(.002)
    numeric['terminal_wall_ns'] = time.time_ns()
    numeric['terminal_monotonic_ns'] = time.monotonic_ns()
    for n, req in enumerate(requests):
        q = decision(req, codes[n]); before = time.monotonic_ns()
        actual = denied(writers[n].fileno(), CONFIRM, q)
        # A completed/closed request and an expired original budget differ.
        want = errno.ETIMEDOUT if before >= req.deadline_monotonic_ns else errno.ECANCELED
        numeric['negatives'].append(dict(index=n, kind='terminal_confirm', input=bytes(q).hex(),
            errno=actual, before_monotonic_ns=before, after_monotonic_ns=time.monotonic_ns()))
        save()
        if actual != want: raise ValueError('late/duplicate confirmation must not restart')


def verify_exchange(r):
    row = r['security_capabilities']; nrow = row['numeric']; mode = r['numeric_comparison']
    if mode not in MODES or nrow['mode'] != mode or r.get('key_agreement') or r.get('unauthenticated_encryption') or r.get('security_cancel_pending'):
        raise ValueError('separate explicit numeric witness required')
    if row['ordinary_denial'].get('confirm_errno') != errno.EPERM:
        raise ValueError('ordinary inherited Managed fd cannot confirm a prompt')
    from sparklink.structs import SleSecurityNegotiationSubmit as Submit
    requests = [decode(Submit, q) for q in row['requests']]
    prompts = [decode(Result, v) for v in nrow['prompts']]
    if len(prompts) != 2 or prompts[0].comparison_code != prompts[1].comparison_code:
        raise ValueError('both independently computed live codes required')
    for n, (q, prompt) in enumerate(zip(requests, prompts)):
        expected = (1, 1, q.generation, q.lifetime, q.handle, q.request_id, q.role)
        for v in [prompt, decode(Result, row['results'][n])]:
            if (v.version, v.profile, v.generation, v.lifetime, v.handle, v.request_id, v.role) != expected or bytes(v.local_caps) != OFFER or bytes(v.peer_caps) != OFFER or v.status:
                raise ValueError('numeric result exact original identity/offer required')
        if (prompt.state, prompt.flags, prompt.error) != (3, 15, 0) or not 0 <= prompt.comparison_code < 1_000_000:
            raise ValueError('live code is not a proof, confirmation or installation')
        if not row['g_start_before_wall_ns'] <= nrow['prompt_wall_ns'] <= nrow['terminal_wall_ns'] <= row['observed_wall_ns'] or not row['t_arm_before_monotonic_ns'] <= nrow['prompt_monotonic_ns'] < q.deadline_monotonic_ns:
            raise ValueError('prompt must retain original deadline')
        final = decode(Result, row['results'][n])
        wanted = (11, 0, 119) if mode == 'numeric-approve' else ((5, -errno.EACCES, 7) if mode == 'numeric-reject' and n == r['index'] else (7, -errno.ETIMEDOUT, 7))
        if (final.state, final.error, final.flags) != wanted or final.comparison_code:
            raise ValueError('exact terminal numeric mechanism state required')
        if mode == 'numeric-approve' and nrow['terminal_monotonic_ns'] >= q.deadline_monotonic_ns:
            raise ValueError('actual installation exceeded original budget')
        if wanted[0] == 7 and nrow['terminal_monotonic_ns'] < q.deadline_monotonic_ns:
            raise ValueError('cannot manufacture early original expiry')
        rows = [v for v in nrow['negatives'] if v['index'] == n]
        terminal = next(v for v in rows if v['kind'] == 'terminal_confirm')
        want = errno.ETIMEDOUT if terminal['before_monotonic_ns'] >= q.deadline_monotonic_ns else errno.ECANCELED
        if len(rows) != 6 or {v['kind']:v['errno'] for v in rows} != dict(code=errno.ESTALE, request=errno.ENOENT, reserved=errno.EINVAL, accept=errno.EINVAL, nonowner=errno.EPERM, terminal_confirm=want):
            raise ValueError('complete numeric decision denials required')
        for v in rows:
            actual = decode(Confirm, v['input']); expected_q = decision(q, prompt.comparison_code)
            if v['kind'] == 'code': expected_q.comparison_code = (prompt.comparison_code + 1) % 1_000_000
            elif v['kind'] == 'request': expected_q.request_id += 1
            elif v['kind'] == 'reserved': expected_q.reserved[0] = 1
            elif v['kind'] == 'accept': expected_q.accept = 2
            if bytes(actual) != bytes(expected_q) or v['after_monotonic_ns'] < v['before_monotonic_ns']:
                raise ValueError('numeric negative must execute the exact original decision')
    expected_indices = [r['index'], 1-r['index']] if mode == 'numeric-approve' else [r['index']] if mode == 'numeric-reject' else []
    if [v['index'] for v in nrow['decisions']] != expected_indices:
        raise ValueError('required explicit original-author decisions missing')
    for v in nrow['decisions']:
        n = v['index']; q = requests[n]
        if bytes(decode(Confirm, v['input'])) != bytes(decision(q, prompts[n].comparison_code, mode == 'numeric-approve')) or not nrow['prompt_monotonic_ns'] <= v['before_monotonic_ns'] <= v['after_monotonic_ns'] < q.deadline_monotonic_ns or not nrow['prompt_wall_ns'] <= v['before_wall_ns'] <= v['after_wall_ns'] <= nrow['terminal_wall_ns']:
            raise ValueError('decisions cannot replace the original deadline or prompt')
    return nrow


def public_comparison(g_public, t_public, ra, rb):
    """Independent OpenSSL CMAC on public transcript, not production decoder.

    Explicit SDK111 whole-message/key reversal. No secret scalar/shared key is
    read. This checks the dialect, not third-party/standard conformance.
    """
    import subprocess
    if [len(v) for v in (g_public, t_public, ra, rb)] != [64, 64, 16, 16]:
        raise ValueError('exact public numeric transcript widths required')
    message = g_public[16:32] + t_public + ra + rb
    result = subprocess.run(['openssl', 'mac', '-macopt', 'cipher:AES-128-CBC',
        '-macopt', 'hexkey:' + g_public[:16][::-1].hex(), 'CMAC'],
        input=message[::-1], capture_output=True, check=True)
    digest = bytes.fromhex(result.stdout.decode().strip())
    if len(digest) != 16:
        raise ValueError('complete CMAC128 output required')
    return int.from_bytes(digest, 'big') % 1_000_000


def corroborate_numeric_decisions(r, commands, g_public, t_public, ra, rb):
    import subprocess
    row = verify_exchange(r)
    number = public_comparison(g_public, t_public, ra, rb)
    if any(decode(Result, p).comparison_code != number for p in row['prompts']):
        raise ValueError('both kernel codes must match independently checked real public transcript')
    if r['numeric_comparison'] == 'numeric-approve':
        for index, controller in [(0x141, r['index']), (0x142, 1-r['index'])]:
            decision_row = next(v for v in row['decisions'] if v['index'] == controller)
            if commands[index][0]['wall_ns'] < decision_row['before_wall_ns']:
                raise ValueError('DH proof cannot submit before local original-author confirmation')
    elif any(index in commands for index in (0x141, 0x142)):
        raise ValueError('reject/expiry cannot submit a DH proof')
    return dict(status='TWO_CODES_AND_PUBLIC_TRANSCRIPT_AND_ORIGINAL_DECISIONS_CHECKED',
        mode=r['numeric_comparison'], code=number, decisions=row['decisions'],
        negative_count=len(row['negatives']),
        openssl=subprocess.check_output(['openssl', 'version'], text=True).strip(),
        scope='Automated privileged mechanism witness; not human confirmation, daemon Agent, trusted Grant or Bond')
