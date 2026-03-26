# Gethes

Gethes is an interactive terminal-driven game experience built with `pygame-ce`.
It combines a stylized in-game console, multiple mini-games, persistent progression,
and a narrative layer centered on Syster.

## What Gethes Is

Gethes merges three systems into one runtime:

- A real-time custom terminal UI rendered in `pygame-ce`.
- Integrated mini-games running inside the same shell-like environment.
- A story-driven assistant (Syster) that reacts to player context and progression.

Everything happens inside the game interface to preserve immersion.

## Core Experience

- Fully customizable visual identity: themes, typography, colors, and adaptive UI scale.
- Text-based story mode with choices, hidden files, and route progression.
- Local mod support for themes and story content.
- Integrated mini-games: Snake, Hangman (1P/2P), Tic-Tac-Toe, CodeBreaker, Physics Lab, and Roguelike.
- Achievement system with in-game notifications and sound cues.
- Multi-slot saves for parallel routes and profiles.
- Multi-language support: Spanish, English, Portuguese, French, and German (with auto-detection).
- Local Syster runtime powered by Mistral through Ollama.
- Auto-update flow through GitHub Releases.
- Domain-supervised runtime (hexagonal baseline) for resilience and fault isolation.
- Cloud sync for presence, scores, preferences, and Syster telemetry.
- Cloud account system (register/login) with news feed pulled from GitHub releases/commits.

## Narrative Direction

In Gethes, the console is the world itself.
Syster is not a generic help panel; it is part of the fiction and responds based on
commands, history progress, and player behavior.

## Project Status

- Current version: `v0.08`
- Status: active development
- Primary platform: Windows
- Recommended distribution: installer (`Setup`) published in GitHub Releases

## Vision

Gethes is evolving toward a modular console visual novel with deeper gameplay loops:

- new narrative routes,
- more mini-games,
- stronger Syster memory and interaction quality,
- and higher production value in presentation and audio-visual feedback.
