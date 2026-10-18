//! Cursor-based directory observations through the pinned daemon. The stream
//! has no background task, Native fd, permission grant, or hardware state cache.
use crate::{ApplicationError, Client};
use slk_channel::deadline::Deadline;
use slk_contract::{ControllerId, controller_events as wire};
use std::{collections::VecDeque, future::Future};

type Result<T> = std::result::Result<T, ApplicationError>;

#[derive(Debug, PartialEq, Eq)]
pub enum ControllerEvent {
    /// Core-validated membership lookup, with a journal cursor taken BEFORE
    /// the lookup. Following hints can duplicate identities seen here. No
    /// atomic Native snapshot or Ready/retirement-drain guarantee is implied.
    Snapshot {
        before: u64,
        controllers: Vec<ControllerId>,
    },
    Published {
        sequence: u64,
        controller: ControllerId,
    },
    Withdrawn {
        sequence: u64,
        controller: ControllerId,
    },
    /// Terminal for this observer. Open a new stream to resnapshot; never
    /// silently resume at the tail and conceal missing observations.
    Gap {
        after: u64,
        oldest: u64,
        current: u64,
    },
}

pub struct ControllerEvents {
    client: Client,
    cursor: u64,
    pending: VecDeque<ControllerEvent>,
    terminal: bool,
}

async fn bounded<T>(
    client: &Client,
    deadline: Deadline,
    work: impl Future<Output = Result<T>>,
) -> Result<T> {
    deadline.remaining()?;
    if client.daemon_lost() {
        return Err(ApplicationError::Identity("daemon owner replaced"));
    }
    let mut lost = client.owner_loss();
    tokio::select! {
        biased;
        _ = lost.changed() => Err(ApplicationError::Identity("daemon owner replaced")),
        result = tokio::time::timeout_at(deadline.instant().into(), work) => {
            result.map_err(|_| std::io::Error::from_raw_os_error(nix::libc::ETIMEDOUT))?
        },
    }
}

impl Client {
    pub async fn controller_events(&self, deadline: Deadline) -> Result<ControllerEvents> {
        let (cursor, controllers) = bounded(self, deadline, async {
            let batch: wire::Batch = self
                .proxy(slk_contract::MANAGER_PATH, slk_contract::MANAGER)
                .await?
                .call(
                    wire::METHOD,
                    &(0u64, false, slk_contract::deadline_wire(deadline.stamp())),
                )
                .await?;
            if !wire::valid(0, &batch) {
                return Err(ApplicationError::Identity("controller journal shape"));
            }
            let controllers = self.controllers().await?;
            self.check_owner().await?;
            deadline.remaining()?;
            Ok((batch.2, controllers))
        })
        .await?;
        let mut pending = VecDeque::new();
        pending.push_back(ControllerEvent::Snapshot {
            before: cursor,
            controllers,
        });
        Ok(ControllerEvents {
            client: self.clone(),
            cursor,
            pending,
            terminal: false,
        })
    }
}

impl ControllerEvents {
    /// Original absolute deadline covers owner checks, RPCs, empty bounded
    /// waits and reply validation. Timeout does not reset the cursor or close
    /// this observer. Cancelling this future cancels observation only.
    pub async fn next(&mut self, deadline: Deadline) -> Result<ControllerEvent> {
        if self.terminal {
            return Err(ApplicationError::Identity(
                "controller stream terminal; resnapshot required",
            ));
        }
        if self.client.daemon_lost() {
            self.pending.clear();
            self.terminal = true;
            return Err(ApplicationError::Identity("daemon owner replaced"));
        }
        let result = bounded(&self.client, deadline, async {
            self.client.check_owner().await?;
            if !self.pending.is_empty() {
                return Ok(None);
            }
            loop {
                let batch: wire::Batch = self
                    .client
                    .proxy(slk_contract::MANAGER_PATH, slk_contract::MANAGER)
                    .await?
                    .call(
                        wire::METHOD,
                        &(
                            self.cursor,
                            true,
                            slk_contract::deadline_wire(deadline.stamp()),
                        ),
                    )
                    .await?;
                self.client.check_owner().await?;
                deadline.remaining()?;
                if !wire::valid(self.cursor, &batch) {
                    return Err(ApplicationError::Identity("controller journal shape"));
                }
                if batch.3 || !batch.4.is_empty() {
                    return Ok(Some(batch));
                }
                // The server can cap one wait. Reuse the SAME original stamp;
                // an empty heartbeat neither advances nor extends this wait.
            }
        })
        .await;
        let batch = match result {
            Ok(batch) => {
                deadline.remaining()?;
                batch
            }
            Err(error) => {
                if !matches!(&error, ApplicationError::Io(e) if e.raw_os_error() == Some(nix::libc::ETIMEDOUT))
                {
                    self.terminal = true;
                    self.pending.clear();
                }
                return Err(error);
            }
        };
        // No await after cursor publication: cancellation while waiting or
        // validating cannot consume a row and lose it from the next call.
        if let Some(batch) = batch {
            if batch.3 {
                self.terminal = true;
                return Ok(ControllerEvent::Gap {
                    after: self.cursor,
                    oldest: batch.1,
                    current: batch.2,
                });
            }
            for row in batch.4 {
                let controller = wire::identity(row);
                self.pending.push_back(if row.3 == wire::PUBLISHED {
                    ControllerEvent::Published {
                        sequence: row.0,
                        controller,
                    }
                } else {
                    ControllerEvent::Withdrawn {
                        sequence: row.0,
                        controller,
                    }
                });
            }
            self.cursor = batch.2;
        }
        self.pending
            .pop_front()
            .ok_or(ApplicationError::Identity("empty controller event batch"))
    }
}
