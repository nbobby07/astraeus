//! Update planning and durable orchestration. Filesystem recovery is supplied by the caller.
mod engine;
mod history;
mod model;
pub mod pacman;

pub use engine::*;
pub use history::*;
pub use model::*;

pub type Result<T> = std::result::Result<T, String>;

#[cfg(test)]
mod tests;
