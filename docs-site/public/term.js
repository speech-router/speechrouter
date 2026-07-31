(() => {
  const live = document.getElementById('sr-live');
  const term = document.getElementById('sr-term');
  if (!live || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const script = [
    ['every', 'every speech', 'every speech model', 'Every speech model.'],
    ['one', 'one api', 'One API.'],
    ['switch', 'switch providers mid', 'switch providers mid-stream', 'Switch providers mid-stream.'],
    ['never', 'never lose', 'never lose a word', 'Never lose a word.'],
  ];
  let u = 0, w = 0;
  const caret = '<span class="sr-caret"></span>';
  const tick = () => {
    const words = script[u];
    const done = w === words.length - 1;
    if (!done) {
      live.innerHTML = '<span class="int">' + words[w] + '</span>' + caret;
      w++;
      setTimeout(tick, 260 + Math.random() * 240);
    } else {
      const t = (u * 1.8 + 0.4).toFixed(2);
      const fin = document.createElement('div');
      fin.className = 'sr-line fin';
      fin.innerHTML = '<span class="ts">' + t + 's</span> ' + words[w];
      term.insertBefore(fin, live);
      live.innerHTML = caret;
      while (term.children.length > 6) term.removeChild(term.firstChild);
      u = (u + 1) % script.length; w = 0;
      setTimeout(tick, 900);
    }
  };
  setTimeout(tick, 700);
})();
