"""Obsidian vault indexer for Qdrant vector database."""

import argparse
import logging
from pathlib import Path

from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def index_vault(vault_path: str, full_reindex: bool = False) -> None:
    """Index Obsidian vault into Qdrant.
    
    Args:
        vault_path: Path to Obsidian vault
        full_reindex: If True, clear existing index and rebuild from scratch
    """
    logger.info(f"Indexing vault: {vault_path}")
    
    vault = Path(vault_path)
    if not vault.exists():
        logger.error(f"Vault path does not exist: {vault_path}")
        return
    
    # TODO: Implement indexing logic
    # 1. Connect to Qdrant
    # 2. Create collection if needed
    # 3. Walk vault directory for .md files
    # 4. Generate embeddings via Ollama
    # 5. Upsert to Qdrant with metadata
    # 6. Handle incremental updates (check file hashes)
    
    markdown_files = list(vault.rglob("*.md"))
    logger.info(f"Found {len(markdown_files)} markdown files")
    
    # Exclude Smart Connections cache
    markdown_files = [
        f for f in markdown_files
        if ".smart-env" not in str(f)
    ]
    logger.info(f"After filtering: {len(markdown_files)} files to index")
    
    logger.info("Indexing complete (stub implementation)")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Index Obsidian vault")
    parser.add_argument(
        "--vault-path",
        default=settings.obsidian_vault_path,
        help="Path to Obsidian vault"
    )
    parser.add_argument(
        "--full-reindex",
        action="store_true",
        help="Clear existing index and rebuild"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    index_vault(args.vault_path, args.full_reindex)


if __name__ == "__main__":
    main()
