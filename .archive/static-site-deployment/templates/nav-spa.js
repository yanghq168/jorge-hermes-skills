(function () {
  var rootPath = "/aivideo/";
  var transitionMs = 180;

  function isAivideoUrl(url) {
    return url.origin === window.location.origin && url.pathname.indexOf(rootPath) === 0;
  }

  function getManagedStyles(doc, baseUrl) {
    return Array.prototype.slice.call(doc.querySelectorAll('link[rel="stylesheet"]')).filter(function (link) {
      return new URL(link.getAttribute("href"), baseUrl || doc.baseURI).pathname.indexOf(rootPath) === 0;
    });
  }

  function markCurrentStyles() {
    getManagedStyles(document, window.location.href).forEach(function (link) {
      link.dataset.aivideoStyle = "true";
    });
  }

  function syncStyles(nextDoc, nextUrl) {
    markCurrentStyles();

    var nextHrefs = getManagedStyles(nextDoc, nextUrl.href).reduce(function (hrefs, link) {
      var href = new URL(link.getAttribute("href"), nextUrl.href).href;
      if (hrefs.indexOf(href) === -1) {
        hrefs.push(href);
      }
      return hrefs;
    }, []);

    Array.prototype.slice.call(document.querySelectorAll('link[data-aivideo-style="true"]')).forEach(function (link) {
      link.parentNode.removeChild(link);
    });

    var pending = nextHrefs.map(function (href) {
      return new Promise(function (resolve) {
        var link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = href;
        link.dataset.aivideoStyle = "true";
        link.onload = resolve;
        link.onerror = resolve;
        document.head.appendChild(link);
      });
    });

    return Promise.all(pending);
  }

  function setPage(nextDoc, url, shouldPush) {
    var currentMain = document.querySelector(".video-page");
    var nextMain = nextDoc.querySelector(".video-page");

    if (!currentMain || !nextMain) {
      window.location.href = url.href;
      return Promise.resolve();
    }

    return syncStyles(nextDoc, url).then(function () {
      document.title = nextDoc.title;
      nextMain.classList.add("is-page-entering");
      currentMain.replaceWith(nextMain);

      if (shouldPush) {
        window.history.pushState({ aivideo: true }, "", url.href);
      }

      void nextMain.offsetWidth;

      requestAnimationFrame(function () {
        nextMain.classList.remove("is-page-entering");
      });

      if (url.hash) {
        var target = document.querySelector(url.hash);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          return;
        }
      }

      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function loadPage(url, shouldPush) {
    var currentMain = document.querySelector(".video-page");

    if (currentMain) {
      currentMain.classList.add("is-page-leaving");
    }

    return fetch(url.href, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Navigation failed");
        }
        return response.text();
      })
      .then(function (html) {
        var nextDoc = new DOMParser().parseFromString(html, "text/html");
        return new Promise(function (resolve) {
          window.setTimeout(resolve, transitionMs);
        }).then(function () {
          return setPage(nextDoc, url, shouldPush);
        });
      })
      .catch(function () {
        window.location.href = url.href;
      });
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a");

    if (!link || link.target || link.hasAttribute("download")) {
      return;
    }

    var url = new URL(link.href, window.location.href);

    if (!isAivideoUrl(url) || url.href === window.location.href) {
      return;
    }

    event.preventDefault();
    loadPage(url, true);
  });

  window.addEventListener("popstate", function () {
    var url = new URL(window.location.href);
    if (isAivideoUrl(url)) {
      loadPage(url, false);
    }
  });

  markCurrentStyles();
})();
