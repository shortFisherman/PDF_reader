import js from '@eslint/js';
import globals from 'globals';

export default [
    {
        ignores: [
            'node_modules/**',
            // 非本项目 JS 的目录/第三方捆绑与历史产物，不在 P2-03 目标内。
            '.agents/**',
            '.codex/**',
            '.comet/**',
            '.opencode/**',
            '.superpowers/**',
            '.worktrees/**',
            'cache/**',
            'docs/**',
            'openspec/**',
            // 历史 fixture：仅被历史 run-alignment-repro runner 读取，不在正式 npm test 中；P3-03 统一结构。
            'static/modules/__tests__/**',
            // 历史诊断 runner：不在 npm test 中；P3-03 统一测试夹具结构。
            'tests/run-alignment-repro-tests.mjs',
            'tests/run-lazy-loader-tests.mjs',
            'tests/run-task-4.4-tests.mjs',
            'tests/run-task-4.5-tests.mjs',
        ],
    },
    js.configs.recommended,
    {
        rules: {
            // 核心规则保持有效；仅允许 `_` 前缀的显式“测试钩子/未用参数”命名约定。
            'no-unused-vars': ['error', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrors: 'none',
            }],
        },
    },
    {
        files: ['static/**/*.js'],
        languageOptions: {
            globals: globals.browser,
        },
    },
    {
        files: ['tests/*.mjs'],
        languageOptions: {
            globals: {
                ...globals.node,
                ...globals.browser,
            },
        },
    },
];
