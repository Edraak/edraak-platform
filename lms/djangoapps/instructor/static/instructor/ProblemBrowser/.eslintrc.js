module.exports = {
  extends: 'eslint-config-edx',
  root: true,
  settings: {
    'import/resolver': {
      webpack: {
        config: 'webpack.dev.config.js',
      },
    },
  },
};
