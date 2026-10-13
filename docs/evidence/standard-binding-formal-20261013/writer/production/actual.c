#include <stdbool.h>
    #include <stdint.h>
    #include <stddef.h>
    #include <stdlib.h>
    #include <errno.h>
    #include <assert.h>
    typedef uint8_t u8;typedef uint16_t u16;
    #define GFP_KERNEL 0
    u8 nondet_u8(void);u16 nondet_u16(void);int nondet_int(void);bool nondet_bool(void);
    struct usb_device{int unused;};
    struct sle_usb_dev{bool active;struct usb_device*udev;u8 command_request_type;u16 command_index;};
    static struct usb_device device;static struct sle_usb_dev context;
    static unsigned allocs,live,controls;static int expected_length,usb_result;static u16 expected_opcode;static int expected_timeout;
    static void*kmalloc(size_t n,int f){(void)f;assert(n>=4&&n<=65535);allocs++;void*p=malloc(n);if(p)live++;return p;}
    static void kfree(void*p){assert(p&&live==1);live--;free(p);}
    static void put_unaligned_le16(u16 n,u8*p){p[0]=(u8)n;p[1]=(u8)(n>>8);}
    static unsigned usb_sndctrlpipe(struct usb_device*d,int ep){assert(d==&device&&ep==0);return 0;}
    static void*bounded_copy(void*dest,const void*src,size_t n){assert(__CPROVER_r_ok(src,n));assert(__CPROVER_w_ok(dest,n));return dest;}
    #define memcpy bounded_copy
    static int usb_control_msg(struct usb_device*d,unsigned pipe,u8 request,u8 type,u16 value,u16 index,void*raw,u16 size,int timeout){
     assert(d==&device&&pipe==0&&request==0&&value==0&&type==context.command_request_type&&index==context.command_index&&timeout==expected_timeout);
     assert(expected_length>=0&&expected_length<=65531&&size==expected_length+4&&__CPROVER_r_ok(raw,size));
     u8*p=raw;assert(p[0]==(u8)expected_opcode&&p[1]==(u8)(expected_opcode>>8));assert(p[2]==(u8)expected_length&&p[3]==(u8)(expected_length>>8));controls++;usb_result=nondet_int();return usb_result;
    }
    int sle_usb_write_command_locked(struct sle_usb_dev *d, u16 opcode,
				 const u8 *params, int plen, int timeout)
{
	u8 *pkt;
	int total, ret;

	if (!d->active || !d->udev)
		return -ENODEV;
	if (plen < 0 || (plen && !params))
		return -EINVAL;
	if (plen > 65531)
		return -EMSGSIZE;
	total = 4 + plen;
	pkt = kmalloc(total, GFP_KERNEL);
	if (!pkt)
		return -ENOMEM;
	put_unaligned_le16(opcode, pkt);
	put_unaligned_le16(plen, pkt + 2);
	if (plen)
		memcpy(pkt + 4, params, plen);
	ret = usb_control_msg(d->udev, usb_sndctrlpipe(d->udev, 0),
		0, d->command_request_type, 0, d->command_index,
		pkt, total, timeout);
	kfree(pkt);
	if (ret < 0)
		return ret;
	return ret == total ? 0 : -EREMOTEIO;
}
    static u8 payload[65531];
    int main(void){context.active=nondet_bool();context.udev=nondet_bool()?&device:NULL;context.command_request_type=nondet_u8();context.command_index=nondet_u16();expected_length=nondet_int();expected_opcode=nondet_u16();expected_timeout=nondet_int();const u8*p=nondet_bool()?payload:NULL;
     int ret=sle_usb_write_command_locked(&context,expected_opcode,p,expected_length,expected_timeout);
     assert(live==0&&controls<=1&&allocs<=1);
     if(!ret){assert(context.active&&context.udev&&controls==1&&expected_length>=0&&expected_length<=65531&&(expected_length==0||p)&&usb_result==4+expected_length);}
     if(!context.active||!context.udev){assert(ret==-ENODEV&&!controls&&!allocs);}
     else if(expected_length<0||(expected_length&&!p)){assert(ret==-EINVAL&&!controls&&!allocs);}
     else if(expected_length>65531){assert(ret==-EMSGSIZE&&!controls&&!allocs);}
     if(controls){assert(ret==(usb_result<0?usb_result:usb_result==expected_length+4?0:-EREMOTEIO));}
    }
    