/* =========================================
   FALTASI INNOVATIONS
   MAIN JAVASCRIPT
========================================= */


document.addEventListener("DOMContentLoaded", function () {


    /* MOBILE MENU */

    const menuToggle = document.getElementById("menuToggle");

    const navigation = document.getElementById("navigation");


    if (menuToggle && navigation) {

        menuToggle.addEventListener("click", function () {

            navigation.classList.toggle("active");

        });

    }



    /* CLOSE MOBILE MENU WHEN LINK IS CLICKED */

    const navigationLinks =
        document.querySelectorAll("#navigation a");


    navigationLinks.forEach(function (link) {

        link.addEventListener("click", function () {

            navigation.classList.remove("active");

        });

    });



    /* SIMPLE SCROLL EFFECT */

    const header =
        document.querySelector(".header");


    window.addEventListener("scroll", function () {

        if (window.scrollY > 50) {

            header.classList.add("scrolled");

        } else {

            header.classList.remove("scrolled");

        }

    });


});