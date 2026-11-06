// Runtime half of the perf wrap plugin: times every onChange subscriber into window.__onChangeMs.
const sink = () => (window.__onChangeMs ??= []);
const timed = (fn) => (...a) => {
  const t = performance.now();
  try {
    return fn(...a);
  } finally {
    sink().push(performance.now() - t);
  }
};
export function perfApi(cb) {
  return (api) => {
    const orig = api.onChange.bind(api);
    api.onChange = (fn) => orig(timed(fn));
    window.__api = api;
    return cb(api);
  };
}
export const perfChange = (fn) => timed(fn);
