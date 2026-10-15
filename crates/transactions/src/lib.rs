//! Update planning and durable orchestration. Filesystem recovery is supplied by the caller.
mod engine;
mod history;
pub mod integration;
pub mod management;
pub mod management_store;
mod model;
pub mod package_integrity;
pub mod pacman;
pub use management::*;
#[cfg(all(target_os = "linux", feature = "native-alpm"))]
pub mod native_alpm;

pub use engine::*;
pub use history::*;
pub use model::*;

pub type Result<T> = std::result::Result<T, String>;

#[cfg(test)]
mod tests;
