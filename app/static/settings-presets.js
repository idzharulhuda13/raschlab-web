(function () {
  function init() {
    var chips = document.querySelectorAll('.chip[data-misfit]');
    if (!chips.length) return;
    var input = document.getElementById('misfit') ||
      document.querySelector('input[name="misfit"]') ||
      document.getElementById('threshold') ||
      document.getElementById('misfit_threshold') ||
      document.querySelector('input[name="threshold"]') ||
      document.querySelector('input[name="misfit_threshold"]') ||
      document.querySelector('input[type="number"]');

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        var val = chip.getAttribute('data-misfit');
        if (input && val) {
          input.value = val;
          input.focus();
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
