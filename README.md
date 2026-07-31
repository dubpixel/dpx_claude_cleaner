<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!--  *** Thanks for checking out the Best-README-Template. If you have a suggestion that would make this better, please fork the repo and create a pull request or simply open an issue with the tag "enhancement". Don't forget to give the project a star! Thanks again! Now go create something AMAZING! :D -->



<!-- /// d   u   b   p   i   x   e   l  ---  f   o   r   k   ////--v0.5.7 -->
<!--this has additionally been modifed by @dubpixel for hardware use -->
<!--search dpx_claude_cleaner.. search & replace is COMMAND OPTION F -->

<!--this is the version for software -->
<!--todo ** add small product image thats not in a details tag -->
<!--todo ** new software product image? Remove it? -->
<!--igure out how to get the details tag to properly render in jekyll for gihub pages.-->



<!-- PROJECT SHIELDS -->
<!-- *** I'm using markdown "reference style" links for readability. Reference links are enclosed in brackets [ ] instead of parentheses ( ). See the bottom of this document for the declaration of the reference variables for contributors-url, forks-url, etc. This is an optional, concise syntax you may use. https://www.markdownguide.org/basic-syntax/#reference-style-links -->
<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]
</div>
<!-- PROJECT LOGO -->
<div align="center">
  <a href="https://github.com/dubpixel/dpx_claude_cleaner">
    <img src="images/logo.png" alt="Logo" height="120">
  </a>
<h1 align="center">dpx_claude_cleaner</h1>
<h3 align="center"><i>a sassy project tag line here</i></h3>
  <p align="center">
    claude youre a messy bitch
    <br />
     »  
     <a href="https://github.com/dubpixel/dpx_claude_cleaner"><strong>Project Here!</strong></a>
     »  
     <br />
    <a href="https://github.com/dubpixel/dpx_claude_cleaner/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    ·
    <a href="https://github.com/dubpixel/dpx_claude_cleaner/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
    </p>
</div>
   <br />
<!-- TABLE OF CONTENTS -->
<details>
  <summary><h3>Table of Contents</h3></summary>
<ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>    
    <li><a href="#reflection">Reflection</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
</ol>
</details>
<!-- ABOUT THE PROJECT -->
<details>
<summary><h3>About The Project</h3></summary>
Claude Code stores every conversation as a `.jsonl` file under
`~/.claude/projects/<encoded-project-path>/`, and those pile up fast — dead
sessions from abandoned projects, empty sessions from accidental launches,
orphaned index entries pointing at files that no longer exist. `dpx_claude_cleaner`
(aka `cc-sessions`) is a single-file, dependency-free Python TUI for cleaning
that up: browse every session across every project, filter by empty/orphan
status, rename, move sessions between projects, or delete them — all without
touching Claude Code's own files except where explicitly documented as safe.

See `CLAUDE.md` for the full on-disk schema this tool reads and writes.
</br>

*author(s): // www.dubpixel.tv  - i@dubpixel.tv | other authors* 
</br>
<h3>Images</h3>

### FRONT
![FRONT][product-front]
</details>
<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

 * Python 3.10+ (stdlib only — `curses`, `argparse`, `json`, `pathlib`)

<!--
 * [![KiCad][KiCad.org]][KiCad-url]
 * [![Fusion360][Fusion-360]][Autodesk-url]
 * [![FastLed][FastLed.io]][FastLed-url]
 * [![Fusion360][Fusion-360]][Autodesk-url]
 * [![Next][Next.js]][Next-url]
 * [![React][React.js]][React-url]
 * [![Vue][Vue.js]][Vue-url]
 * [![Angular][Angular.io]][Angular-url]
 * [![Svelte][Svelte.dev]][Svelte-url]
 * [![Laravel][Laravel.com]][Laravel-url]
 * [![Bootstrap][Bootstrap.com]][Bootstrap-url]
 * [![JQuery][JQuery.com]][JQuery-url]
 
-->
<p align="right">(<a href="#readme-top">back to top</a>)</p>
<!-- GETTING STARTED -->

## Getting Started

  ### Prerequisites
  * Python 3.10 or newer (no pip packages required)

  ### Installation

  1. Clone the repo and run the script directly — nothing to build or install:
     ```bash
     git clone https://github.com/dubpixel/dpx_claude_cleaner.git
     cd dpx_claude_cleaner
     python3 src/cc-sessions-v3.py --version
     ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## Usage

```bash
# Interactive TUI (default)
python3 src/cc-sessions-v3.py

# Print stats by project and exit
python3 src/cc-sessions-v3.py analyze

# Interactive CLI to clean orphan index entries / add unindexed sessions
python3 src/cc-sessions-v3.py fix-orphans

# Point at a non-default ~/.claude directory
python3 src/cc-sessions-v3.py --root /path/to/.claude
```

Full TUI keybindings and column-flag reference are in `CLAUDE.md`.

<!-- REFLECTION -->
## Reflection

* what did we learn?
  - Claude Code's `sessions-index.json` isn't reliably kept in sync with the
    filesystem as of ~v2.1.30, so any cleanup tool needs a filesystem scan as
    a source of truth, not just the index.
* what do we like/hate?
  - Single-file + stdlib-only keeps it trivially portable, at the cost of a
    fairly dense one-file codebase as features grow.
* what would/could we do differently?
  - Split index I/O and TUI rendering into separate modules if this grows
    much further.

  <!-- ROADMAP -->
## Roadmap

- [ ] Fix `--help`/`help` mode printing `None` (see open issues)
- [ ] Scope session discovery so it only picks up genuine Claude session files
- [ ] Make unindexed `msg_count` scanning lazy for large (8+ MB) sessions

See the [open issues](https://github.com/dubpixel/dpx_claude_cleaner/issues) for a full list of proposed features (and known issues).

<!-- CONTRIBUTING -->
## Contributing

_Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**._

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Top contributors:
<a href="https://github.com/dubpixel/dpx_claude_cleaner/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dubpixel/dpx_claude_cleaner" alt="contrib.rocks image" />
</a>

<!-- LICENSE -->
## License
Distributed under the MIT License. See `LICENSE.txt` for more information.
<!-- CONTACT -->
## Contact

  ### Joshua Fleitell - i@dubpixel.tv

  Project Link: [https://github.com/dubpixel/dpx_claude_cleaner](https://github.com/dubpixel/dpx_claude_cleaner)

<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

<!--
  * [ ]() - the best !
-->

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/dubpixel/dpx_claude_cleaner.svg?style=flat-square
[contributors-url]: https://github.com/dubpixel/dpx_claude_cleaner/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/gdubpixel/dpx_claude_cleaner.svg?style=flat-square
[forks-url]: https://github.com/dubpixel/dpx_claude_cleaner/network/members
[stars-shield]: https://img.shields.io/github/stars/dubpixel/dpx_claude_cleaner.svg?style=flat-square
[stars-url]: https://github.com/dubpixel/dpx_claude_cleaner/stargazers
[issues-shield]: https://img.shields.io/github/issues/dubpixel/dpx_claude_cleaner.svg?style=flat-square
[issues-url]: https://github.com/dubpixel/dpx_claude_cleaner/issues
[license-shield]: https://img.shields.io/github/license/dubpixel/dpx_claude_cleaner.svg?style=flat-square
[license-url]: https://github.com/dubpixel/dpx_claude_cleaner/blob/main/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=flat-square&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/jfleitell
[product-front]: images/front.png
[product-rear]: images/rear.png
[product-front-rendering]: images/front_render.png
[product-rear-rendering]: images/rear_render.png
[product-pcbFront]: images/pcb_front.png
[product-pcbRear]: images/pcb_rear.png
[Next.js]: https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white
[Next-url]: https://nextjs.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[Vue.js]: https://img.shields.io/badge/Vue.js-35495E?style=for-the-badge&logo=vuedotjs&logoColor=4FC08D
[Vue-url]: https://vuejs.org/
[Angular.io]: https://img.shields.io/badge/Angular-DD0031?style=for-the-badge&logo=angular&logoColor=white
[Angular-url]: https://angular.io/
[Svelte.dev]: https://img.shields.io/badge/Svelte-4A4A55?style=for-the-badge&logo=svelte&logoColor=FF3E00
[Svelte-url]: https://svelte.dev/
[Laravel.com]: https://img.shields.io/badge/Laravel-FF2D20?style=for-the-badge&logo=laravel&logoColor=white
[Laravel-url]: https://laravel.com
[Bootstrap.com]: https://img.shields.io/badge/Bootstrap-563D7C?style=for-the-badge&logo=bootstrap&logoColor=white
[Bootstrap-url]: https://getbootstrap.com
[JQuery.com]: https://img.shields.io/badge/jQuery-0769AD?style=for-the-badge&logo=jquery&logoColor=white
[JQuery-url]: https://jquery.com 
[KiCad.org]: https://img.shields.io/badge/KiCad-v8.0.6-blue
[KiCad-url]: https://kicad.org 
[Fusion-360]: https://img.shields.io/badge/Fusion360-v4.2.0-green
[Autodesk-url]: https://autodesk.com 
[FastLed.io]: https://img.shields.io/badge/FastLED-v3.9.9-red
[FastLed-url]: https://fastled.io 
