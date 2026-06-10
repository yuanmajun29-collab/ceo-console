#!/usr/bin/env node
/**
 * Agent Coordinator hook - run before starting codex agent.
 */
import path from 'path';
import { fileURLToPath } from 'url';
import { findProjectRoot, injectCoordinatorContext } from '../inject-context.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = findProjectRoot(__dirname);
injectCoordinatorContext('codex', root);
