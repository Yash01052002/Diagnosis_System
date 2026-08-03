document.querySelectorAll(".copy").forEach(btn=>{
  btn.addEventListener("click", async ()=>{
    const code=btn.parentElement.querySelector("code").innerText;
    try{
      await navigator.clipboard.writeText(code);
      const old=btn.innerText; btn.innerText="Copied!";
      setTimeout(()=>btn.innerText=old,1200);
    }catch(e){btn.innerText="Select manually";}
  });
});
const themeBtn=document.getElementById("themeBtn");
themeBtn.addEventListener("click",()=>{
  document.body.classList.toggle("light");
  themeBtn.textContent=document.body.classList.contains("light")?"☀":"☾";
});
