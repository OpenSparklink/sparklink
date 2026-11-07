#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline corroboration of ROM READM before upload; never cold identification.

Reuses paired USB capture readers and HCC/upload evidence. No device access.
Runtime register observations remain guest records, not an independent decoder.
"""
from ws73_capture import CaptureError, check_capture_stats
from ws73_boot_code_evidence import successful_in
from ws73_firmware_upload_evidence import successful_out, corroborate as uploaded
from ws73_model_evidence import corroborate_rows as hcc_model
from ws73_rom_chip import COMMAND, observe_candidate, validate_directusb_reply


def corroborate_directusb_read_only(capture, capture_stats, executor, guest):
    """One selected ROM exchange, not the reset/upload/HCC qualification below.

    Existing raw USB readers are independent of the nusb completion report.
    Caller still binds source/artifact, selected physical topology and VM origin.
    This gate does not establish cold power, controller drain, or access validity.
    """
    check_capture_stats(capture_stats)
    try:
        raw = validate_directusb_reply(executor, guest)
    except ValueError as error:
        raise CaptureError(str(error)) from error
    if (type(executor.get('bus')) is not int or not 1 <= executor['bus'] <= 255 or
            type(executor.get('device_number_observation')) is not int or
            not 1 <= executor['device_number_observation'] <= 127):
        raise CaptureError('explicit observed guest USB identity required')
    outgoing = successful_out(capture)
    incoming = successful_in(capture, require_drained=True)
    if len(outgoing) != 1 or len(incoming) != 1:
        raise CaptureError('exactly one isolated command and response required')
    request, reply = outgoing[0], incoming[0]
    identity = executor['bus'], executor['device_number_observation']
    if (request['raw'] != COMMAND or
            any((row['bus'], row['device']) != identity for row in [request, reply]) or
            not request['record'] < request['completion_record'] < reply['submit_record'] < reply['record'] or
            not reply['successful'] or reply['requested'] != 512 or reply['length'] != 4 or
            reply['raw'] != raw):
        raise CaptureError('isolated ROM capture differs from exact executor exchange')
    return dict(status='ISOLATED_ROM_EXCHANGE_CORROBORATED_NOT_IDENTIFICATION',
                command_record=request['record'], command_completion=request['completion_record'],
                receive_submit=reply['submit_record'], receive_completion=reply['record'],
                raw=raw.hex(), bus=identity[0], device=identity[1],
                candidate=observe_candidate(raw), cold_power_verified=False,
                access_validity_proven=False, automatic_selection_permitted=False,
                scope='One exact USB exchange and nusb report; no startup/HCC, firmware, '
                      'cold power, silicon authentication, cancellation/drain or recovery qualification')


def corroborate_rows(outgoing, incoming, probe):
    if (probe.get('boot_origin')!='SOFTWARE_REGISTER_RESET_NOT_COLD_POWER' or
            probe.get('automatic_firmware_selection') is not False or
            probe.get('read_validity_proven') is not False or
            probe.get('rom_chip_expected') not in ('E','U')):
        raise CaptureError('explicit software-origin candidate scope required')
    selected=[v for v in outgoing if v['raw']==COMMAND]
    observations=probe.get('rom_chip_reads',[])
    if len(selected)!=3 or len(observations)!=3:
        raise CaptureError('three exact ROM commands/observations required')
    identities={(v['bus'],v['device']) for v in selected}
    if len(identities)!=1:
        raise CaptureError('one actual ROM USB identity required')
    identity=next(iter(identities));pairs=[]
    mutations=[v['record'] for v in outgoing if (v['bus'],v['device'])==identity and
               v['raw'].startswith((b'FILES ',b'WRITEM '))]
    if not mutations:
        raise CaptureError('subsequent explicit actual upload required')
    for index,(request,observed) in enumerate(zip(selected,observations,strict=True)):
        later=[v['record'] for v in outgoing if v['record']>request['completion_record']]
        if not later:raise CaptureError('missing following boot transaction')
        replies=[v for v in incoming if (v['bus'],v['device'])==identity and
                 request['completion_record']<v['submit_record']<v['record']<min(later)]
        if len(replies)!=1:raise CaptureError('one exact paired chip READM response required')
        reply=replies[0]
        if not reply['successful'] or reply['requested']!=512 or reply['length']!=4 or len(reply['raw'])!=4:
            raise CaptureError('complete untruncated four-byte ROM response required')
        if reply['record']>=min(mutations):
            raise CaptureError('chip observation must precede ALL calibration writes/upload')
        try:candidate=observe_candidate(reply['raw'])
        except ValueError as error:raise CaptureError(str(error)) from error
        if (observed.get('command')!=COMMAND.hex() or observed.get('reply')!=reply['raw'].hex() or
                observed.get('out_actual')!=len(COMMAND) or observed.get('in_actual')!=4 or
                candidate['model']!=probe['rom_chip_expected'] or candidate['bus']!='USB'):
            raise CaptureError('actual ROM bytes differ from explicit board/guest observation')
        pairs.append(dict(index=index,command_record=request['record'],command_completion=request['completion_record'],
                          receive_submit=reply['submit_record'],receive_completion=reply['record'],
                          raw=reply['raw'].hex(),bus=identity[0],device=identity[1],**{
                              k:candidate[k] for k in ['little_endian_u32','zero_reply_ambiguous']}))
    expected=pairs[0]['raw']
    if any(v['raw']!=expected for v in pairs):raise CaptureError('unstable ROM register')
    for name in ['runtime_chip_before','runtime_chip_after']:
        values=probe.get(name,[])
        if len(values)!=3 or any(v.get('raw')!=expected for v in values):
            raise CaptureError('complete matching before/after guest register records required')
    hcc=hcc_model(outgoing,incoming)
    if hcc['observation']['model']!='WS73'+probe['rom_chip_expected']:
        raise CaptureError('actual post-upload HCC disagrees with known board/ROM')
    if max(v['receive_completion'] for v in pairs)>=hcc['observation']['request_record']:
        raise CaptureError('HCC observation must follow ROM transaction')
    return dict(status='ACTUAL_SOFT_ROM_BYTES_CORROBORATED_IDENTIFICATION_UNPROVED',pairs=pairs,
                first_mutation_record=min(mutations),hcc=hcc,
                cold_power_verified=False,access_validity_proven=False,automatic_selection_permitted=False,
                scope='Actual ROM bytes before explicit upload plus real HCC; runtime words from guest records. No cold power/access validity/automatic selection/attestation or natural recovery qualification')


def corroborate(capture,probe,firmware_directory):
    outgoing=successful_out(capture);incoming=successful_in(capture)
    result=corroborate_rows(outgoing,incoming,probe)
    result['upload']=uploaded(outgoing,firmware_directory)
    chunks=[c for image in result['upload']['images'] for c in image['chunks']]
    identity=result['pairs'][0]
    if (any((c['bus'],c['device'])!=(identity['bus'],identity['device']) for c in chunks) or
            max(c['completion_record'] for c in chunks)>=result['hcc']['observation']['request_record']):
        raise CaptureError('same-ROM-device upload must complete before runtime HCC')
    return result
