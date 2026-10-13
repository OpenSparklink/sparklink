#include <assert.h>
#include <stdbool.h>
    #include <stdint.h>
    #include <stddef.h>
    #include <string.h>
    #include <errno.h>
    typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
    #define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
    struct sle_usb_capabilities {
	u16 command_max;
	u16 acb_length;
	u16 icb_length;
	u8 acb_count;
	u8 icb_count;
	u8 features[10];
};
    struct sle_usb_dev { bool active,metadata_valid;void*udev;u8 version[5],mac_addr[6],command_credits;u32 fw_version;struct sle_usb_capabilities capabilities;};
    static u16 get_unaligned_le16(const u8*p){return p[0]|(u16)p[1]<<8;}
    static u32 get_unaligned_le32(const u8*p){return p[0]|(u32)p[1]<<8|(u32)p[2]<<16|(u32)p[3]<<24;}
    static void*memchr_inv(const void*p,int c,unsigned n){const u8*b=p;for(unsigned i=0;i<n;i++)if(b[i]!=(u8)c)return(void*)(b+i);return NULL;}
    #define SLE_OP_RESET              0x0408
#define SLE_OP_READ_LOCAL_VERSION 0x0404
#define SLE_OP_READ_CMD_LENGTH    0x0401
#define SLE_OP_READ_BUFFER        0x0402
#define SLE_OP_READ_FEATURES      0x0403
#define SLE_OP_READ_MAC_ADDR      0x0406
#define SLE_EVT_CMD_COMPLETE      0x0002
    u8 nondet_u8(void);int nondet_int(void);struct sle_usb_capabilities nondet_caps(void);
    static unsigned calls;
    static u8 responses[6][18];
    static int sle_usb_send_cmd_sync(struct sle_usb_dev*d,u16 op,const u8*p,int n,u8*r,int capacity,int*len){
     (void)d;assert(calls<6);assert(capacity==64);assert(n==(op==SLE_OP_READ_MAC_ADDR?1:0));assert(!n||(p&&*p==0));
     unsigned index=calls++;for(unsigned i=0;i<18;i++){responses[index][i]=nondet_u8();r[i]=responses[index][i];}*len=nondet_int();return nondet_int();
    }
    int sle_usb_validate_init_reply(const u8 *resp, int len,
				       u16 opcode, int return_size)
{
	if (len != 8 + return_size ||
	    get_unaligned_le16(resp) != SLE_EVT_CMD_COMPLETE ||
	    get_unaligned_le16(resp + 2) != 4 + return_size ||
	    get_unaligned_le16(resp + 4) != opcode)
		return -EPROTO;
	if (resp[7])
		return -EREMOTEIO;
	return 0;
}
int sle_usb_dev_init_controller_locked(struct sle_usb_dev *d)
{
	static const struct { u16 opcode; int result_size; } queries[] = {
		{ SLE_OP_RESET, 0 },
		{ SLE_OP_READ_LOCAL_VERSION, 5 },
		{ SLE_OP_READ_CMD_LENGTH, 2 },
		{ SLE_OP_READ_BUFFER, 6 },
		{ SLE_OP_READ_FEATURES, 10 },
		{ SLE_OP_READ_MAC_ADDR, 6 },
	};
	struct sle_usb_capabilities capabilities = {};
	u8 resp[64], version[5], mac_addr[6];
	const u8 address_type = 0; /* alliance-assigned identifier */
	int resp_len, ret;
	size_t i;

	if (!d->active || !d->udev)
		return -ENODEV;
	d->metadata_valid = true;
	for (i = 0; i < ARRAY_SIZE(queries); i++) {
		const u8 *params = queries[i].opcode == SLE_OP_READ_MAC_ADDR ?
			&address_type : NULL;

		ret = sle_usb_send_cmd_sync(d, queries[i].opcode, params,
			params ? 1 : 0, resp, sizeof(resp), &resp_len);
		if (ret)
			return ret;
		ret = sle_usb_validate_init_reply(resp, resp_len,
			queries[i].opcode, queries[i].result_size);
		if (ret)
			return ret;
		if (i + 1 < ARRAY_SIZE(queries) && !resp[6])
			return -EAGAIN;
		switch (queries[i].opcode) {
		case SLE_OP_READ_LOCAL_VERSION:
			memcpy(version, resp + 8, sizeof(version));
			break;
		case SLE_OP_READ_CMD_LENGTH:
			capabilities.command_max = get_unaligned_le16(resp + 8);
			if (capabilities.command_max < 255)
				return -EPROTO;
			break;
		case SLE_OP_READ_BUFFER:
			capabilities.acb_length = get_unaligned_le16(resp + 8);
			capabilities.acb_count = resp[10];
			capabilities.icb_length = get_unaligned_le16(resp + 11);
			capabilities.icb_count = resp[13];
			if (capabilities.acb_length > 2047 || capabilities.icb_length > 2047 ||
			    (!capabilities.acb_length != !capabilities.acb_count) ||
			    (!capabilities.icb_length != !capabilities.icb_count))
				return -EPROTO;
			break;
		case SLE_OP_READ_FEATURES:
			memcpy(capabilities.features, resp + 8, sizeof(capabilities.features));
			break;
		case SLE_OP_READ_MAC_ADDR:
			memcpy(mac_addr, resp + 8, sizeof(mac_addr));
			if (!memchr_inv(mac_addr, 0, sizeof(mac_addr)) ||
			    !memchr_inv(mac_addr, 0xff, sizeof(mac_addr)))
				return -EPROTO;
			break;
		}
	}
	/* io_lock protects the complete observation and its validity bit. */
	d->fw_version = get_unaligned_le32(version); /* legacy projection only */
	memcpy(d->version, version, sizeof(d->version));
	d->capabilities = capabilities;
	d->command_credits = resp[6];
	memcpy(d->mac_addr, mac_addr, sizeof(mac_addr));
	d->metadata_valid = true;
	return 0;
}
int main(void){
     struct sle_usb_dev d={.active=true,.metadata_valid=true,.udev=&d,.fw_version=42,.version={9,9,9,9,9},.mac_addr={8,8,8,8,8,8},.command_credits=7,.capabilities=nondet_caps()};
     struct sle_usb_dev old=d;int ret=sle_usb_dev_init_controller_locked(&d);assert(calls<=6);
     if(ret){assert(!d.metadata_valid);assert(d.fw_version==old.fw_version&&d.command_credits==old.command_credits);assert(!memcmp(d.version,old.version,5)&&!memcmp(d.mac_addr,old.mac_addr,6));assert(!memcmp(&d.capabilities,&old.capabilities,sizeof(d.capabilities)));}
     else {assert(calls==6&&d.metadata_valid);assert(d.capabilities.command_max>=255);assert(d.capabilities.acb_length<=2047&&d.capabilities.icb_length<=2047);assert((!d.capabilities.acb_length)==(!d.capabilities.acb_count));assert((!d.capabilities.icb_length)==(!d.capabilities.icb_count));assert(!memcmp(d.version,responses[1]+8,5));assert(!memcmp(d.capabilities.features,responses[4]+8,10));assert(!memcmp(d.mac_addr,responses[5]+8,6));assert(d.command_credits==responses[5][6]);assert(memchr_inv(d.mac_addr,0,6)&&memchr_inv(d.mac_addr,255,6));}
    }
    