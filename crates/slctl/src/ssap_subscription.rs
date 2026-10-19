//! Finite daily-interaction workflow over the sole public SDK subscription.
//! No protocol loop,authorization cache,retry or implicit lease renewal.
use libsparklink::{ApplicationConnection, Deadline};
use std::{io::Write, time::Duration};

pub(crate) fn mode(value: &str) -> anyhow::Result<u8> {
    match value {
        "notify" => Ok(1),
        "indicate" => Ok(2),
        "both" => Ok(3),
        _ => anyhow::bail!("invalid local receive mode"),
    }
}
struct Options {
    handle: u16,
    modes: u8,
    count: usize,
    lease_ms: u32,
}
impl Options {
    fn parse(args: &[&str]) -> anyhow::Result<Self> {
        if !(1..=4).contains(&args.len()) {
            anyhow::bail!(
                "ssap-subscribe CONNECTION HANDLE [notify|indicate|both] [COUNT] [LEASE_MS]"
            );
        }
        let result = Self {
            handle: args[0].parse()?,
            modes: mode(args.get(1).copied().unwrap_or("both"))?,
            count: args.get(2).copied().unwrap_or("8").parse()?,
            lease_ms: args.get(3).copied().unwrap_or("60000").parse()?,
        };
        if result.handle == 0
            || !(1..=4096).contains(&result.count)
            || !(250..=60000).contains(&result.lease_ms)
        {
            anyhow::bail!("nonzero handle,count1..4096,lease250..60000ms required");
        }
        Ok(result)
    }
}
pub(crate) async fn run(link: &ApplicationConnection, args: &[&str]) -> anyhow::Result<()> {
    let options = Options::parse(args)?;
    let mut subscription = link
        .ssap()
        .subscribe(
            vec![options.handle],
            options.modes,
            options.lease_ms,
            Deadline::after(Duration::from_secs(5))?,
        )
        .await?;
    println!(
        "SsapSubscription: path={} token={} epoch={} expires_ns={} count_at_least={}",
        link.path(),
        subscription.info().token,
        subscription.info().security_epoch,
        subscription.info().expires_ns,
        options.count
    );
    std::io::stdout().flush()?;
    let mut observed_cleanup=None;
    let outcome: anyhow::Result<usize>=async {
        let mut received=0;
        while received<options.count {
            let batch=tokio::select!{
                signal=tokio::signal::ctrl_c()=>{signal?;anyhow::bail!("subscription interrupted;last delivery may be uncertain");},
                result=subscription.read(true,Deadline::after(Duration::from_secs(5))?)=>result?,
            };
            if batch.info.state==3 && batch.flags==1 {observed_cleanup=Some(batch.clone());}
            for packet in &batch.packets {
                let decoded=slk_protocol::ssap::updates::Update::decode(2048,&packet.pdu)
                    .map_err(|e|anyhow::anyhow!("incoming display codec: {e:?}"))?;
                for item in decoded.items {
                    println!("SsapSubscriptionIncoming: path={} sequence={} epoch={} kind={} handle={} value={} raw={}",
                        link.path(),packet.sequence,packet.security_epoch,
                        if packet.indication{"indicate"}else{"notify"},item.handle,
                        crate::commands::hex_bytes(item.value),crate::commands::hex_bytes(&packet.pdu));
                }
                received+=1;
            }
            println!("SsapSubscriptionBatch: last={} received={} dropped={} refused={} state={}",
                batch.last_sequence,received,batch.dropped_notifications,batch.refused_indications,batch.info.state);
            std::io::stdout().flush()?;
            if batch.info.state>=2 && received<options.count {
                anyhow::bail!("subscription ended before requested packet count");
            }
        }
        Ok(received)
    }.await;
    // Always attempt the same original token's cleanup;never create another
    // lease to conceal a timeout,interrupt or malformed/lost receipt.
    let cleanup = match observed_cleanup {
        Some(batch)=>Ok(batch),
        None=>subscription.close(Deadline::after(Duration::from_secs(5))?).await,
    };
    match (outcome, cleanup) {
        (Ok(received), Ok(batch)) => {
            println!(
                "SsapSubscriptionReleased: token={} received={} flags={} reason={} discarded={}",
                batch.info.token, received, batch.flags, batch.reason, batch.discarded_on_close
            );
            Ok(())
        }
        (Err(error), Ok(_)) => Err(error.context("remote CPCD cleanup confirmed")),
        (Ok(_), Err(error)) => Err(anyhow::anyhow!(
            "subscription cleanup not confirmed: {error}"
        )),
        (Err(error), Err(cleanup)) => {
            Err(error.context(format!("subscription cleanup not confirmed: {cleanup}")))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finite_explicit_parameters_and_original_one_shot_modes() {
        let defaults = Options::parse(&["17"]).unwrap();
        assert_eq!(
            (
                defaults.handle,
                defaults.modes,
                defaults.count,
                defaults.lease_ms
            ),
            (17, 3, 8, 60000)
        );
        for (name, value) in [("notify", 1), ("indicate", 2), ("both", 3)] {
            assert_eq!(mode(name).unwrap(), value);
            let selected = Options::parse(&["65535", name, "4096", "250"]).unwrap();
            assert_eq!(
                (
                    selected.handle,
                    selected.modes,
                    selected.count,
                    selected.lease_ms
                ),
                (65535, value, 4096, 250)
            );
        }
        for args in [
            vec![],
            vec!["0"],
            vec!["65536"],
            vec!["17", "unknown"],
            vec!["17", "both", "0"],
            vec!["17", "both", "4097"],
            vec!["17", "both", "1", "249"],
            vec!["17", "both", "1", "60001"],
            vec!["17", "both", "1", "5000", "extra"],
        ] {
            assert!(Options::parse(&args).is_err(), "{args:?}");
        }
    }
}
