%% Cost optimisation
clear all
clc

A = [];
b = [];
Aeq = [1 0 0];
beq = [5];
lb = [0 0 0.99];
ub = [];
nonlcon = [];
options = optimoptions('fmincon','FunctionTolerance', 1e-8,'Display','iter','OptimalityTolerance',1e-8);
x0 = [5,0.01, 1];
x = fmincon(@System,x0,A,b,Aeq,beq,lb,ub,nonlcon,options)