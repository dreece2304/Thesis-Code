%% Cost optimisation
clear all
clc

A = [];
b = [];
Aeq = [1 0 0];
beq = [5];
lb = [0 0 0];
ub = [];
nonlcon = [];
options = optimoptions('fmincon','FunctionTolerance', 1e-5,'Display','iter','OptimalityTolerance',1e-5);
x0 = [5,0.1, 1.5];
x = fmincon(@System,x0,A,b,Aeq,beq,lb,ub,nonlcon,options)