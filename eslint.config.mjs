import js from '@eslint/js';
import globals from 'globals';

export default [
    {
        ignores: [
            'node_modules/**',
            // Python 环境与构建产物目录：第三方/生成 JS 不属于本项目 lint 目标。
            'venv/**',
            '.venv/**',
            'build/**',
            // 非本项目 JS 的目录/第三方捆绑与历史产物，不在 P2-03 目标内。
            '.agents/**',
            '.codex/**',
            '.comet/**',
            '.opencode/**',
            '.worktrees/**',
            'cache/**',
            'docs/**',
            // 历史诊断 runner/fixture：P3-03 起归档在 tests/history/，不进入正式测试与 lint。
            'tests/history/**',
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
