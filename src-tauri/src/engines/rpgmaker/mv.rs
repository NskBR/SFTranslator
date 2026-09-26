use std::path::Path;

use crate::Game;

use super::mz;

pub(super) fn integration_ready(root: &Path) -> bool {
    mz::integration_ready(root)
}

pub(super) fn install(root: &Path, game: &Game, port: u16) -> Result<(), String> {
    mz::install_variant(root, game, port, "MV")
}
